# diagnose_camera_v2.py - The Intelligent Diagnostic Tool

from pyorbbecsdk import *

def main():
    print("--- Camera Hardware Alignment Diagnostic Tool v2 ---")
    print("Searching for the BEST available Color+Depth profile pair for HW alignment...")

    pipeline = None
    try:
        pipeline = Pipeline()
        all_color_profiles = pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        if not all_color_profiles:
            print("\nCRITICAL: No color sensor profiles found. Check camera connection.")
            return

        valid_pairs = []
        
        # Phase 1: Data Collection (Silently find all valid pairs)
        for i in range(len(all_color_profiles)):
            color_profile = all_color_profiles[i].as_video_stream_profile()
            color_format = color_profile.get_format()

            # We only care about formats OpenCV can easily use.
            if color_format not in [OBFormat.BGR, OBFormat.RGB]:
                continue

            try:
                hw_d2c_profile_list = pipeline.get_d2c_depth_profile_list(color_profile, OBAlignMode.HW_MODE)
                if hw_d2c_profile_list and len(hw_d2c_profile_list) > 0:
                    # Found at least one compatible depth profile. Let's save it.
                    # For simplicity, we'll just take the first compatible depth profile.
                    depth_profile = hw_d2c_profile_list[0].as_video_stream_profile()
                    
                    valid_pairs.append({
                        "color_width": color_profile.get_width(),
                        "color_height": color_profile.get_height(),
                        "color_format": color_profile.get_format(),
                        "color_format_str": str(color_profile.get_format()).replace("OBFormat.",""),
                        "depth_width": depth_profile.get_width(),
                        "depth_height": depth_profile.get_height(),
                        "depth_format_str": str(depth_profile.get_format()).replace("OBFormat.",""),
                        "fps": color_profile.get_fps()
                    })
            except Exception:
                # Ignore profiles that cause errors
                continue

        # Phase 2: Analysis and Reporting
        if not valid_pairs:
            print("\n" + "="*60)
            print("DIAGNOSTIC COMPLETE: NO VALID HW-D2C PAIRS FOUND.")
            print("This suggests a potential issue with camera firmware or SDK version.")
            print("Consider trying Software Alignment (SW_MODE) as a fallback.")
            print("="*60)
            return
            
        # Sort the results to find the best one.
        # Priority 1: Highest Resolution (width * height), descending
        # Priority 2: Highest FPS, descending
        # Priority 3: Prefer BGR format over RGB
        format_priority = {'BGR': 0, 'RGB': 1}
        sorted_pairs = sorted(
            valid_pairs,
            key=lambda p: (-(p['color_width'] * p['color_height']), -p['fps'], format_priority.get(p['color_format_str'], 99)),
            reverse=False # The key itself handles the descending logic with negative signs
        )

        print("\n" + "="*60)
        print("DIAGNOSTIC COMPLETE: Found the following compatible HW-D2C pairs:")
        print("Sorted from best to worst based on Resolution > FPS > Format\n")
        
        # Print a formatted table header
        header = f"{'Width':<8}{'Height':<8}{'FPS':<5}{'Color Fmt':<12}{'Depth Fmt':<12}"
        print(header)
        print("-" * len(header))

        for pair in sorted_pairs:
            print(f"{pair['color_width']:<8}{pair['color_height']:<8}{pair['fps']:<5}{pair['color_format_str']:<12}{pair['depth_format_str']:<12}")

        # Explicitly state the best choice
        best_choice = sorted_pairs[0]
        print("\n--- RECOMMENDATION ---")
        print("For the best performance in this project, use the following parameters in your camera_thread.py:")
        print(f"  - Width:  {best_choice['color_width']}")
        print(f"  - Height: {best_choice['color_height']}")
        print(f"  - Format: OBFormat.{best_choice['color_format_str']}")
        print(f"  - FPS:    {best_choice['fps']}")
        print("="*60)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()