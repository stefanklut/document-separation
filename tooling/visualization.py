import argparse
import functools
import json
import logging
import random
import sys
from concurrent.futures import ThreadPoolExecutor as ThreadPool
from pathlib import Path
from typing import Optional

import cv2
import matplotlib.pyplot as plt
import numpy as np
from natsort import os_sorted
from PIL import Image
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parent.joinpath("..")))
from utils.logging_utils import get_logger_name

logger = logging.getLogger(get_logger_name())


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualization of prediction/GT of model")

    io_args = parser.add_argument_group("IO")
    # io_args.add_argument("-t", "--train", help="Train input folder/file",
    #                         nargs="+", action="extend", type=str, default=None)
    io_args.add_argument("-i", "--input", help="Input folder/file", nargs="+", action="extend", type=str, default=None)
    io_args.add_argument("-o", "--output", help="Output folder", type=str)

    args = parser.parse_args()

    return args


IMAGE_PRELOAD = 16

_keypress_result = None


def keypress(event):
    global _keypress_result
    # print('press', event.key)
    if event.key in ["q", "escape"]:
        sys.exit()
    if event.key in [" ", "right"]:
        _keypress_result = "forward"
        return
    if event.key in ["backspace", "left"]:
        _keypress_result = "back"
        return
    if event.key in ["e", "delete"]:
        _keypress_result = "delete"
        return
    if event.key in ["w"]:
        _keypress_result = "bad"
        return


def on_close(event):
    sys.exit()


@functools.lru_cache(maxsize=IMAGE_PRELOAD * 2)
def get_image(image_path: str) -> Optional[np.ndarray]:
    image_path = Path(image_path)

    # Check if thumbnail exists
    thumbnail_path = Path("/data/thumbnails/").joinpath(str(image_path.relative_to(Path("/"))) + ".thumbnail.jpg")
    try:
        image = Image.open(thumbnail_path)
        image.load()
        image = image.convert("RGB")
    except OSError as e:
        print(f"Could not open thumbnail {thumbnail_path}. Trying to open original image")
        try:
            image = Image.open(image_path.resolve())
            image.load()
            image = image.convert("RGB")
        except OSError as e:
            print(f"Could not open image {image_path}")
            return None
    return np.asarray(image)


def main(args) -> None:
    """
    Currently running the validation set and showing the ground truth and the prediction side by side

    Args:
        args (argparse.Namespace): arguments for where to find the images
    """
    combined_jsons = {}
    for json_path in args.input:
        json_path = Path(json_path)
        if not json_path.is_file():
            raise ValueError(f"Could not find file {json_path}")
        if not json_path.suffix == ".json":
            raise ValueError(f"File {json_path} is not a json file")
        with json_path.open(mode="r") as f:
            combined_jsons.update(json.load(f))

    loader = os_sorted(list(combined_jsons.keys()))

    bad_results = np.zeros(len(loader), dtype=bool)
    delete_results = np.zeros(len(loader), dtype=bool)

    fig, axes = plt.subplots(1)
    if not isinstance(axes, (list, np.ndarray)):
        axes = [axes]  # Ensure axes is a list
    fig.tight_layout()
    fig.canvas.mpl_connect("key_press_event", keypress)
    fig.canvas.mpl_connect("close_event", on_close)
    axes[0].axis("off")
    fig_manager = plt.get_current_fig_manager()
    if fig_manager is None:
        raise ValueError("Could not find figure manager")
    fig_manager.window.showMaximized()

    pool = ThreadPool(4)

    for i in range(min(IMAGE_PRELOAD, len(loader))):
        image_path = loader[i]
        pool.submit(get_image, image_path)

    i = 0
    while 0 <= i < len(loader):
        image_path = loader[i]
        data = combined_jsons[image_path]

        fig_manager.window.setWindowTitle(str(image_path))

        # HACK Just remove the previous axes, I can't find how to resize the image otherwise
        axes[0].clear()
        axes[0].axis("off")

        image = get_image(image_path)

        border = 10
        color = [255, 0, 0] if data["result"] == 1 else [255, 255, 255]
        image = cv2.copyMakeBorder(image, border, border, border, border, cv2.BORDER_CONSTANT, value=color)

        if image is None:
            image = np.zeros((100, 100, 3), dtype=np.uint8)

        axes[0].imshow(image)
        if i + IMAGE_PRELOAD < len(loader):
            pool.submit(get_image, loader[i + IMAGE_PRELOAD])

        suptitle = f"{i+1}/{len(loader)}: {Path(image_path).name} result: {data['result']} confidence: {data['confidence']:.2f}"

        if delete_results[i]:
            suptitle += " DELETE"
        elif bad_results[i]:
            suptitle += " BAD"

        fig.suptitle(suptitle)
        # f.title(inputs["file_name"])
        global _keypress_result
        _keypress_result = None
        fig.canvas.draw()
        while _keypress_result is None:
            plt.waitforbuttonpress()
        if _keypress_result == "delete":
            # print(i+1, f"{inputs['original_file_name']}: DELETE")
            delete_results[i] = not delete_results[i]
            bad_results[i] = False
        elif _keypress_result == "bad":
            # print(i+1, f"{inputs['original_file_name']}: BAD")
            bad_results[i] = not bad_results[i]
            delete_results[i] = False
        elif _keypress_result == "forward":
            # print(i+1, f"{inputs['original_file_name']}")
            i += 1
        elif _keypress_result == "back":
            # print(i+1, f"{inputs['original_file_name']}: DELETE")
            i -= 1

    if args.output and (delete_results.any() or bad_results.any()):
        output_dir = Path(args.output)
        if not output_dir.is_dir():
            logger.info(f"Could not find output dir ({output_dir}), creating one at specified location")
            output_dir.mkdir(parents=True)
        if delete_results.any():
            output_delete = output_dir.joinpath("delete.txt")
            with output_delete.open(mode="w") as f:
                for i in delete_results.nonzero()[0]:
                    path = Path(loader[i])
                    line = path.relative_to(output_dir) if path.is_relative_to(output_dir) else path.resolve()
                    f.write(f"{line}\n")
        if bad_results.any():
            output_bad = output_dir.joinpath("bad.txt")
            with output_bad.open(mode="w") as f:
                for i in bad_results.nonzero()[0]:
                    path = Path(loader[i])
                    line = path.relative_to(output_dir) if path.is_relative_to(output_dir) else path.resolve()
                    f.write(f"{line}\n")

        remaining_results = np.logical_not(np.logical_or(bad_results, delete_results))
        if remaining_results.any():
            output_remaining = output_dir.joinpath("correct.txt")
            with output_remaining.open(mode="w") as f:
                for i in remaining_results.nonzero()[0]:
                    path = Path(loader[i])
                    line = path.relative_to(output_dir) if path.is_relative_to(output_dir) else path.resolve()
                    f.write(f"{line}\n")
    pool.shutdown()


if __name__ == "__main__":
    args = get_arguments()
    main(args)
