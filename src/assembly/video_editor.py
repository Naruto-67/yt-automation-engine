import os
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips

def assemble_video(video_path, audio_path, output_path="final_video.mp4"):
    """
    Combines the background video and the TTS audio.
    Automatically loops the video if it's too short to fit the audio.
    """
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at {video_path}")
        return False
        
    if not os.path.exists(audio_path):
        print(f"Error: Audio file not found at {audio_path}")
        return False

    try:
        print("Loading media into the editor...")
        video_clip = VideoFileClip(video_path)
        audio_clip = AudioFileClip(audio_path)

        # THE FIX: If the video is shorter than the audio, we loop it!
        if video_clip.duration < audio_clip.duration:
            print(f"Video ({video_clip.duration}s) is shorter than Audio ({audio_clip.duration}s). Looping video...")
            # Calculate exactly how many times we need to duplicate the video to cover the audio
            loops_needed = int(audio_clip.duration // video_clip.duration) + 1
            
            # Stitch the duplicates together
            video_clip = concatenate_videoclips([video_clip] * loops_needed)

        print(f"Trimming video to exactly {audio_clip.duration} seconds...")
        # Now we can safely cut the video to match the audio length perfectly
        final_video = video_clip.subclipped(0, audio_clip.duration)
        
        # Attach our generated voiceover to the video
        final_video = final_video.with_audio(audio_clip)

        print("Rendering final video. This might take a minute...")
        final_video.write_videofile(
            output_path, 
            fps=30, 
            codec="libx264", 
            audio_codec="aac",
            preset="ultrafast",
            logger=None
        )
        
        # Clean up memory
        video_clip.close()
        audio_clip.close()
        final_video.close()
        
        print(f"Success! Final video rendered to {output_path}")
        return True

    except Exception as e:
        print(f"Failed to assemble video: {e}")
        return False

if __name__ == "__main__":
    assemble_video("test_video.mp4", "test_audio.mp3", "master_final_video.mp4")
