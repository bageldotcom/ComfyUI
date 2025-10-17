import os
import shutil
from datetime import datetime

class SaveVideo:
    """
    Custom ComfyUI node: Save video to disk

    This utility node saves video files to ComfyUI's output directory.
    Compatible with all Bagel video generation nodes.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("VIDEO",),
                "filename_prefix": ("STRING", {"default": "bagel_video"})
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_video"
    CATEGORY = "bagel/video"

    def save_video(self, video, filename_prefix):
        """
        Save video to ComfyUI output directory

        Args:
            video: Video file path (from video generation nodes)
            filename_prefix: Prefix for output filename

        Returns:
            dict: Contains saved file path for ComfyUI UI
        """
        # ComfyUI output directory (standard location)
        output_dir = os.path.join(os.path.dirname(__file__), "..", "..", "output")
        os.makedirs(output_dir, exist_ok=True)

        # Generate unique filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{filename_prefix}_{timestamp}.mp4"
        output_path = os.path.join(output_dir, output_filename)

        # Copy video from temp location to output directory
        shutil.copy2(video, output_path)

        # Clean up temp file
        try:
            os.unlink(video)
        except:
            pass  # Ignore if temp file already deleted

        print(f"✅ Video saved to: {output_path}")

        # Return results for ComfyUI UI
        return {
            "ui": {
                "videos": [{
                    "filename": output_filename,
                    "subfolder": "",
                    "type": "output"
                }]
            }
        }

# Register node
NODE_CLASS_MAPPINGS = {
    "SaveVideo": SaveVideo
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveVideo": "Save Video"
}
