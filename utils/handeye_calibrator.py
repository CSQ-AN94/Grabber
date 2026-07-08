import cv2
import numpy as np
import time
from controllers.arm_controller import ArmController
from sensors.camera_thread import CameraThread

class HandEyeCalibrator:
    """
    一键式自动化手眼标定工具

    支持两种标定板：
    - "chessboard"（默认）：普通棋盘格，纯黑白方格，无marker。用
      cv2.findChessboardCorners + solvePnP 检测。不需要猜字典型号，但要求
      每次拍照必须完整看到所有内角点（不像ChArUco能容忍部分遮挡）。
    - "charuco"：棋盘格+ArUco标记组合，能容忍部分遮挡，但要额外确认ArUco字典型号。

    不管哪种板子，chessboard_square_length / chessboard_corners（或 charuco 对应
    的几个尺寸参数）必须跟实际打印/测量的板子完全一致，否则要么检测不到，要么
    解出来的位置整体按比例偏。
    """
    def __init__(self,
                 arm_controller: ArmController,
                 camera_thread: CameraThread,
                 board_type: str = "chessboard",
                 # --- 普通棋盘格参数（board_type="chessboard"时用）---
                 chessboard_corners: tuple = (6, 9),   # (内角点列数, 内角点行数) = (方格列数-1, 方格行数-1)，实测板子7x10格
                 chessboard_square_length: float = 0.024,  # 单个方格边长，米
                 # --- ChArUco参数（board_type="charuco"时用，保留兼容）---
                 squares_x: int = 9,
                 squares_y: int = 12,
                 square_length: float = 0.030,
                 marker_length: float = 0.0225,
                 aruco_dict_id: int = None):

        self.arm_controller = arm_controller
        self.camera_thread = camera_thread
        self.board_type = board_type
        self.camera_matrix = None
        self.dist_coeffs = None

        if board_type == "chessboard":
            self.chessboard_corners = tuple(chessboard_corners)
            cols, rows = self.chessboard_corners
            objp = np.zeros((cols * rows, 3), dtype=np.float32)
            objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * chessboard_square_length
            self.chessboard_objp = objp
        elif board_type == "charuco":
            if aruco_dict_id is None:
                aruco_dict_id = cv2.aruco.DICT_5X5_250
            # 机器人上实测 cv2==4.5.4，用的是旧版 aruco API（没有 DetectorParameters()/
            # CharucoBoard() 无参构造，只有 *_create 系列），下面用旧式调用保证兼容。
            self.aruco_dict = cv2.aruco.Dictionary_get(aruco_dict_id)
            self.aruco_params = cv2.aruco.DetectorParameters_create()
            self.board = cv2.aruco.CharucoBoard_create(
                squares_x, squares_y,
                square_length,
                marker_length,
                self.aruco_dict,
            )
        else:
            raise ValueError(f"未知 board_type: {board_type!r}，只能是 'chessboard' 或 'charuco'")

    def _find_pattern_in_image(self, image):
        """在图像中定位标定板，返回标定板在相机坐标系下的位姿（target2cam）。"""
        if self.board_type == "chessboard":
            return self._find_chessboard(image)
        return self._find_charuco(image)

    def _find_chessboard(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

        # 优先用更鲁棒的 findChessboardCornersSB（新算法，内部自带高精度角点定位，
        # 实测对光照/清晰度不理想的真实照片明显比经典 findChessboardCorners 更容易
        # 成功检测）。找不到该函数（老版本OpenCV）时回退到经典方法+cornerSubPix。
        if hasattr(cv2, "findChessboardCornersSB"):
            found, corners = cv2.findChessboardCornersSB(
                gray, self.chessboard_corners,
                flags=cv2.CALIB_CB_EXHAUSTIVE + cv2.CALIB_CB_ACCURACY,
            )
        else:
            found, corners = cv2.findChessboardCorners(
                gray, self.chessboard_corners,
                flags=cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE,
            )
            if found:
                criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
                corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

        if not found:
            return None

        ok, rvec, tvec = cv2.solvePnP(
            self.chessboard_objp, corners, self.camera_matrix, self.dist_coeffs,
        )
        if not ok:
            return None

        R, _ = cv2.Rodrigues(rvec)
        T_target_to_cam = np.eye(4)
        T_target_to_cam[:3, :3] = R
        T_target_to_cam[:3, 3] = tvec.flatten()
        return T_target_to_cam

    def _find_charuco(self, image):
        corners, ids, _ = cv2.aruco.detectMarkers(image, self.aruco_dict, parameters=self.aruco_params)
        if ids is None or len(ids) < 4:  # 至少看到4个marker才够插值棋盘格角点
            return None

        num_corners, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            corners, ids, image, self.board,
            cameraMatrix=self.camera_matrix, distCoeffs=self.dist_coeffs,
        )
        if num_corners < 4 or charuco_ids is None:
            return None

        ok, rvec, tvec = cv2.aruco.estimatePoseCharucoBoard(
            charuco_corners, charuco_ids, self.board,
            self.camera_matrix, self.dist_coeffs, rvec=None, tvec=None,
        )
        if not ok:
            return None

        R, _ = cv2.Rodrigues(rvec)
        T_target_to_cam = np.eye(4)
        T_target_to_cam[:3, :3] = R
        T_target_to_cam[:3, 3] = tvec.flatten()
        return T_target_to_cam
    
    def run_calibration_process(self, calibration_poses_deg):
        """
        Eye-in-hand 标定：相机装在手腕上跟末端一起动（比如 left_wrist_0/right_wrist_0），
        标定板固定不动放在环境里，移动手臂让腕部相机从不同角度看到固定的标定板。

        calibration_poses_deg: 关节角度列表（度），需保证每个姿态下标定板都能被
        该手臂的腕部相机看到。建议先用 pose_reader.py 手动遥操/拖动示教采集。
        """
        print("--- Starting Eye-in-Hand Hand-Eye Calibration (camera on wrist) ---")

        self.camera_matrix, self.dist_coeffs = self.camera_thread.get_camera_intrinsics()
        if self.camera_matrix is None:
            print("Error: Could not get camera intrinsics. Aborting.")
            return None

        base_to_end_transforms = []
        target_to_cam_transforms = []
        for i, pose in enumerate(calibration_poses_deg):
            print(f"\nMoving to calibration pose {i+1}/{len(calibration_poses_deg)}...")
            self.arm_controller.move_to_joints(pose)
            time.sleep(3.5)  # 确保机械臂（带着腕部相机）完全静止再拍照

            color_image, _ = self.camera_thread.get_latest_frames()
            if color_image is None:
                print(f"Pose {i+1}: Could not get image. Skipping.")
                continue
            T_base_to_end = self.arm_controller.get_base_to_end_pose_matrix()
            # _find_pattern_in_image 直接返回 PnP 解出的 target2cam（标定板在相机坐标系下的位姿）
            T_target_to_cam = self._find_pattern_in_image(color_image)

            if T_target_to_cam is not None:
                print(f"Pose {i+1}: Pattern found\nT_target_to_cam:{T_target_to_cam}\n")
                base_to_end_transforms.append(T_base_to_end)
                target_to_cam_transforms.append(T_target_to_cam)
            else:
                print(f"Pose {i+1}: Pattern NOT found (标定板不在相机视野内或被遮挡). Skipping.")

        if len(base_to_end_transforms) < 5:
            print("Error: Not enough valid poses collected. Need at least 5. Aborting.")
            return None

        print(f"\nCollected {len(base_to_end_transforms)} valid data pairs. Solving eye-in-hand AX=XB...")

        R_base_to_end = [T[:3, :3] for T in base_to_end_transforms]
        t_base_to_end = [T[:3, 3] for T in base_to_end_transforms]
        # target2cam 直接用 PnP 的测量值（不取逆——OpenCV约定 estimatePoseBoard/
        # estimatePoseCharucoBoard 返回的 rvec/tvec 本身就是 target->camera 的变换）
        R_target_to_cam = [T[:3, :3] for T in target_to_cam_transforms]
        t_target_to_cam = [T[:3, 3] for T in target_to_cam_transforms]

        R_end_to_camera, t_end_to_camera = cv2.calibrateHandEye(
            R_base_to_end, t_base_to_end,
            R_target_to_cam, t_target_to_cam,
            method=cv2.CALIB_HAND_EYE_PARK
        )

        T_end_to_camera = np.eye(4)
        T_end_to_camera[:3, :3] = R_end_to_camera
        T_end_to_camera[:3, 3] = t_end_to_camera.squeeze()

        print("\nEye-in-Hand Calibration successful!")
        print("Resulting T_end_to_camera (4x4 Transformation Matrix):\n", T_end_to_camera)
        return T_end_to_camera

    def run_eye_to_hand_calibration(self, calibration_poses_deg):
        """
        Eye-to-hand 标定：相机固定不动（例如头部相机，标定期间及标定后都不能再动头部
        俯仰/旋转舵机，否则本次标定结果失效），标定板固定装在夹爪/末端上，移动手臂让
        板子依次出现在相机视野的不同位置/角度。

        与 run_calibration_process()（eye-in-hand，相机装在手腕上跟末端一起动）的
        区别只在于：这里动的是标定板（跟着手臂），不动的是相机；数学上通过把
        T_base_to_end 换成其逆矩阵喂给 cv2.calibrateHandEye 来切换到 eye-to-hand 模式，
        解出来的是固定的 T_base_to_camera（相机在基座坐标系下的位姿），而不是 T_end_to_camera。

        calibration_poses_deg: 关节角度列表（度），需保证每个姿态下标定板都能被相机看到。
        建议先用 pose_reader.py 手动遥操，边看相机画面边记录合适的姿态。
        """
        print("--- Starting Eye-to-Hand Hand-Eye Calibration (static camera) ---")

        self.camera_matrix, self.dist_coeffs = self.camera_thread.get_camera_intrinsics()
        if self.camera_matrix is None:
            print("Error: Could not get camera intrinsics. Aborting.")
            return None

        base_to_end_transforms = []
        target_to_cam_transforms = []
        for i, pose in enumerate(calibration_poses_deg):
            print(f"\nMoving to calibration pose {i+1}/{len(calibration_poses_deg)}...")
            self.arm_controller.move_to_joints(pose)
            time.sleep(3.5)  # 确保机械臂（带着标定板）完全静止再拍照

            color_image, _ = self.camera_thread.get_latest_frames()
            if color_image is None:
                print(f"Pose {i+1}: Could not get image. Skipping.")
                continue
            T_base_to_end = self.arm_controller.get_base_to_end_pose_matrix()
            # _find_pattern_in_image 直接返回 PnP 解出的 target2cam（标定板在相机坐标系下的位姿）
            T_target_to_cam = self._find_pattern_in_image(color_image)

            if T_target_to_cam is not None:
                print(f"Pose {i+1}: Pattern found\nT_target_to_cam:{T_target_to_cam}\n")
                base_to_end_transforms.append(T_base_to_end)
                target_to_cam_transforms.append(T_target_to_cam)
            else:
                print(f"Pose {i+1}: Pattern NOT found (标定板不在相机视野内或被遮挡). Skipping.")

        if len(base_to_end_transforms) < 5:
            print("Error: Not enough valid poses collected. Need at least 5. Aborting.")
            return None

        print(f"\nCollected {len(base_to_end_transforms)} valid data pairs. Solving eye-to-hand AX=XB...")

        # eye-to-hand 技巧：把 base2gripper（T_base_to_end 的逆）喂进第一组参数位置，
        # target2cam 直接用 PnP 的测量值（不取逆）。输出的 R/t 此时代表 cam2base。
        R_base_to_gripper, t_base_to_gripper = [], []
        for T in base_to_end_transforms:
            T_inv = np.linalg.inv(T)
            R_base_to_gripper.append(T_inv[:3, :3])
            t_base_to_gripper.append(T_inv[:3, 3])

        R_target_to_cam = [T[:3, :3] for T in target_to_cam_transforms]
        t_target_to_cam = [T[:3, 3] for T in target_to_cam_transforms]

        # calibrateHandEye 内部固定把输出叫"cam2gripper"，但因为我们把 base2gripper
        # （而不是常规的 gripper2base）喂给了第一组参数，这个输出直接就是 cam2base，
        # 即 P_base = output @ P_cam —— 正好是我们要的 T_base_to_camera，不需要再取逆。
        # （之前这里多取了一次逆，是我自己重新推导时发现的bug，已修正。）
        R_cam_to_base, t_cam_to_base = cv2.calibrateHandEye(
            R_base_to_gripper, t_base_to_gripper,
            R_target_to_cam, t_target_to_cam,
            method=cv2.CALIB_HAND_EYE_PARK
        )

        T_base_to_camera = np.eye(4)
        T_base_to_camera[:3, :3] = R_cam_to_base
        T_base_to_camera[:3, 3] = t_cam_to_base.squeeze()

        print("\nEye-to-Hand Calibration successful!")
        print("Resulting T_base_to_camera (4x4 Transformation Matrix):\n", T_base_to_camera)

        self._print_consistency_check(T_base_to_camera, base_to_end_transforms, target_to_cam_transforms)
        return T_base_to_camera

    def _print_consistency_check(self, T_base_to_camera, base_to_end_transforms, target_to_cam_transforms):
        """自洽性验证：标定板刚性固定在末端上，所以对每一组姿态反推出的
        T_gripper_target（标定板相对末端的位姿）理论上应该是同一个常数，
        跟具体姿态无关。这里算出每组姿态反推的T_gripper_target，看它们
        彼此之间的平移/旋转分散程度——分散得越小，标定越可信；分散很大
        说明标定不准（哪怕每张图都成功检测到了棋盘格）。
        """
        T_cam_to_base = np.linalg.inv(T_base_to_camera)
        gripper_targets = []
        for T_base_end, T_cam_target in zip(base_to_end_transforms, target_to_cam_transforms):
            T_gripper_target = np.linalg.inv(T_base_end) @ T_base_to_camera @ T_cam_target
            gripper_targets.append(T_gripper_target)

        translations = np.array([T[:3, 3] for T in gripper_targets])
        mean_t = translations.mean(axis=0)
        dists = np.linalg.norm(translations - mean_t, axis=1)

        rotvecs = np.array([cv2.Rodrigues(T[:3, :3])[0].flatten() for T in gripper_targets])
        mean_rotvec = rotvecs.mean(axis=0)
        angle_errs_deg = np.degrees(np.linalg.norm(rotvecs - mean_rotvec, axis=1))

        print("\n--- 自洽性验证（标定板相对末端的位姿，理论上每组姿态应该算出同一个值）---")
        print(f"平移分散: mean={np.round(mean_t, 4)} m, "
              f"各组离均值距离: max={dists.max()*1000:.1f}mm, mean={dists.mean()*1000:.1f}mm")
        print(f"旋转分散: 各组离均值角度: max={angle_errs_deg.max():.2f}deg, mean={angle_errs_deg.mean():.2f}deg")
        if dists.max() < 0.01 and angle_errs_deg.max() < 2.0:
            print("=> 一致性良好（平移<1cm，旋转<2度），标定结果可信。")
        elif dists.max() < 0.03 and angle_errs_deg.max() < 5.0:
            print("=> 一致性中等（平移<3cm，旋转<5度），可用但精度有限，抓取时留足容错空间。")
        else:
            print("=> 一致性较差，标定结果存疑，建议检查标定板是否松动/姿态数量和多样性是否足够后重新标定。")