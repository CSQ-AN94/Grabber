from pyorbbecsdk import *

def main():
    print("--- Litmus Test for a Specific Camera Profile ---")

    # These are the exact parameters recommended by the diagnostic tool.
    # We are testing the BEST recommended option.
    TARGET_WIDTH = 640
    TARGET_HEIGHT = 480
    TARGET_FORMAT = OBFormat.BGR
    TARGET_FPS = 60

    print(f"Attempting to initialize with:")
    print(f"  - Width:  {TARGET_WIDTH}")
    print(f"  - Height: {TARGET_HEIGHT}")
    print(f"  - Format: {TARGET_FORMAT}")
    print(f"  - FPS:    {TARGET_FPS}")

    pipeline = None
    try:
        pipeline = Pipeline()
        config = Config()

        # Get the master list of color profiles
        profile_list = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        if not profile_list:
            print("\n[FAIL] Could not get any color profiles from the camera.")
            return

        # Find the specific color profile we want to test
        color_profile = profile_list.get_video_stream_profile(
            TARGET_WIDTH, TARGET_HEIGHT, TARGET_FORMAT, TARGET_FPS
        )

        if not color_profile:
            print(f"\n[FAIL] The specific color profile ({TARGET_WIDTH}x{TARGET_HEIGHT}@{TARGET_FPS} {TARGET_FORMAT}) could not be found.")
            return
        
        print("\n[SUCCESS] Successfully found the target color profile.")

        # The critical test: does this specific profile support HW D2C?
        hw_d2c_profile_list = pipeline.get_d2c_depth_profile_list(color_profile, OBAlignMode.HW_MODE)

        if not hw_d2c_profile_list or len(hw_d2c_profile_list) == 0:
            print("\n[FAIL] Even though the color profile exists, the SDK reports NO compatible hardware-aligned depth profiles for it.")
            print("This is the point of failure.")
            return

        depth_profile = hw_d2c_profile_list[0]
        print(f"[SUCCESS] Found a compatible HW-aligned depth profile: {depth_profile}")
        
        # If we reached here, it means the combination is valid. Let's try to start it.
        config.enable_stream(color_profile)
        config.enable_stream(depth_profile)
        config.set_align_mode(OBAlignMode.HW_MODE)
        
        print("\nAttempting to start the pipeline with this configuration...")
        pipeline.start(config)
        print("\n[ULTIMATE SUCCESS] Pipeline started successfully!")
        
        # Let it run for a moment
        time.sleep(1)
        
        pipeline.stop()
        print("[ULTIMATE SUCCESS] Pipeline stopped successfully.")

    except Exception as e:
        print(f"\n[CRITICAL FAIL] An unexpected exception occurred: {e}")
    finally:
        print("\n--- Litmus Test Finished ---")

if __name__ == "__main__":
    main()
