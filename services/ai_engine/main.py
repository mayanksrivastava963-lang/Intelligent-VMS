import argparse
import json
import logging
import math
from pathlib import Path
from time import perf_counter

import cv2

if __package__:
    from .detection.detector import ObjectDetector, draw_detections
    from .tracking.tracker import create_tracker, update_tracker
else:
    from detection.detector import ObjectDetector, draw_detections
    from tracking.tracker import create_tracker, update_tracker


logger = logging.getLogger(__name__)


def local_file(path):
    source = Path(path.strip().strip('"')).expanduser()
    if not source.is_file():
        raise ValueError("Source must be an existing local file")
    return str(source)


def process_image(image_path, detector=None, display=True):
    frame = cv2.imread(local_file(image_path))
    if frame is None:
        raise ValueError("Unable to decode image")
    detector = detector if detector is not None else ObjectDetector()
    try:
        detections = detector.detect(frame)
        if display:
            cv2.imshow("Intelligent VMS", draw_detections(frame, detections))
            cv2.waitKey(0)
        return detections
    finally:
        if display:
            cv2.destroyAllWindows()


def process_video(video_path, detector=None, display=True, sample_every=1, max_frames=None,
                  tracker=None):
    if not isinstance(sample_every, int) or sample_every < 1:
        raise ValueError("sample_every must be a positive integer")
    if max_frames is not None and (not isinstance(max_frames, int) or max_frames < 1):
        raise ValueError("max_frames must be a positive integer")
    capture = cv2.VideoCapture(local_file(video_path))
    processed = 0
    frames_read = 0
    inference_seconds = 0.0
    last_timestamp = None
    latest_tracks = []
    try:
        if not capture.isOpened():
            raise ValueError("Unable to open video")
        detector = detector if detector is not None else ObjectDetector()
        started = perf_counter()
        while True:
            success, frame = capture.read()
            if not success:
                if frames_read == 0:
                    raise ValueError("Video contains no decodable frames")
                break
            frame_index = frames_read
            frames_read += 1
            if frame_index % sample_every:
                continue
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            last_timestamp = timestamp if math.isfinite(timestamp) and timestamp >= 0 else None
            before = perf_counter()
            detections = detector.detect(frame)
            inference_seconds += perf_counter() - before
            if tracker is not None:
                if last_timestamp is None:
                    raise ValueError("Tracking requires valid decoder timestamps")
                latest_tracks = update_tracker(tracker, detections, last_timestamp)
                detections = []
                for track in latest_tracks:
                    if track["observed"]:
                        detections.append(track)
            processed += 1
            if display:
                cv2.imshow("Intelligent VMS", draw_detections(frame, detections))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            if max_frames is not None and processed >= max_frames:
                break
        elapsed = perf_counter() - started
        result = {"frames_read": frames_read, "frames_processed": processed,
                "elapsed_seconds": elapsed,
                "processing_fps": processed / elapsed if elapsed else 0.0,
                "mean_detection_ms": 1000 * inference_seconds / processed,
                "last_video_timestamp_seconds": last_timestamp}
        if tracker is not None:
            result["tracks_created"] = tracker["next_id"] - 1
            result["latest_tracks"] = latest_tracks
        return result
    finally:
        capture.release()
        if display:
            cv2.destroyAllWindows()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local AI detection validation runner")
    parser.add_argument("mode", nargs="?", choices=["image", "video"])
    parser.add_argument("source", nargs="?")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--sample-every", type=int, default=1)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--track", action="store_true")
    parser.add_argument("--camera-id", default="local-video")
    parser.add_argument("--max-missing-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        if args.mode is None:
            print("1. Image Detection\n2. Video Detection")
            args.mode = {"1": "image", "2": "video"}.get(input("Enter your choice: ").strip())
            if args.mode is None:
                raise ValueError("Invalid choice")
        if args.source is None:
            args.source = input("Enter local file path: ")
        source = local_file(args.source)
        if args.sample_every < 1 or (args.max_frames is not None and args.max_frames < 1):
            raise ValueError("Frame limits must be positive integers")
        tracker = None
        if args.track:
            if args.mode != "video":
                raise ValueError("Tracking is available only for video")
            tracker = create_tracker(args.camera_id, args.max_missing_seconds)
        detector = ObjectDetector(args.confidence, args.device)
        if args.mode == "image":
            result = process_image(source, detector, not args.headless)
        else:
            result = process_video(source, detector, not args.headless,
                                   args.sample_every, args.max_frames, tracker)
        print(json.dumps(result, indent=2))
        return 0
    except (KeyboardInterrupt, EOFError):
        logger.info("Stopped by operator")
        return 130
    except Exception as error:
        logger.error("Processing failed (%s). Check local input, model cache and device availability.",
                     type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
