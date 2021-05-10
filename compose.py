import numpy as np

from typing import Callable, Tuple
from PIL import Image, ImageDraw, ImageFont

Frame = np.ndarray


def dummy_info(*args):
    return "PSNR:24.07070707\nSSIM:228.14888"


class FontConfig:
    def __init__(
        self,
        canvas_size_wh: Tuple[int, int],
        sample_text: str,
        font: str = "arial",
        location: Tuple[float, float] = (0.0, 1.0),
        color: Tuple[int, int, int] = (255, 255, 0),
        rel_max_size: Tuple[float, float] = (0.5, 0.75),
    ):
        self.font = font
        self.location = location
        self.color = color
        self.rel_max_size = rel_max_size
        self._determine_optimal_font_size(canvas_size_wh, sample_text)

    def _determine_optimal_font_size(self, canvas_size_wh, sample_text: str):
        max_font_size = 100
        desired_h = canvas_size_wh[1] * self.rel_max_size[0]
        desired_w = canvas_size_wh[0] * self.rel_max_size[1]
        for font_size in range(1, max_font_size + 1, 2):
            font = ImageFont.truetype(self.font + ".ttf", size=font_size)
            w, h = font.getsize(sample_text)
            if w > desired_w or h > desired_h:
                self.optimal_font_size = font_size - 1
                return
        self.optimal_font_size = max_font_size


def _check_frame_pair_is_correct(left_frame: Frame, right_frame: Frame):
    if left_frame is None and right_frame is None:
        return np.zeros(shape=(1, 1, 3), dtype=np.uint8), np.zeros(
            shape=(1, 1, 3), dtype=np.uint8
        )
    if left_frame is None:
        return np.zeros_like(right_frame), right_frame
    if right_frame is None:
        return left_frame, np.zeros_like(left_frame)
    assert (
        len(left_frame.shape) == 3 and left_frame.shape[-1] == 3
    ), "Frames are expected to be 3-channel colored images"
    if left_frame.shape != right_frame.shape:
        smallest = min(left_frame.shape, right_frame.shape)
        return (
            left_frame[: smallest[0], : smallest[1]],
            right_frame[: smallest[0], : smallest[1]],
        )
    return left_frame, right_frame


def ComposeVerticalSplit(
    left_frame: Frame, right_frame: Frame, left_fraction: float = 0.50
):
    left_frame, right_frame = _check_frame_pair_is_correct(left_frame, right_frame)
    merged_frame = np.copy(right_frame)
    threshold = int(left_fraction * left_frame.shape[1])
    merged_frame[:, :threshold] = left_frame[:, :threshold]
    return merged_frame


def ComposeChessPattern(left_frame: Frame, right_frame: Frame, cell_size: float = 0.25):
    _check_frame_pair_is_correct(left_frame, right_frame)
    raise NotImplementedError("Implement ComposeChessPattern")


def ComposeSideBySide(left_frame: Frame, right_frame: Frame):
    _check_frame_pair_is_correct(left_frame, right_frame)
    return np.hstack(left_frame, right_frame)


class Composer:
    def __init__(self, compose_type: str, font_config: FontConfig, canvas_size_wh=None):
        if compose_type == "split":
            self.compose_func = ComposeVerticalSplit
        elif compose_type == "sbs":
            self.compose_func = ComposeSideBySide
        else:
            self.compose_func = ComposeChessPattern
        self.info_provide_func = dummy_info
        self.font_config = font_config
        self.optimal_font_size = None
        self.font = ImageFont.truetype(
            self.font_config.font + ".ttf", size=self.font_config.optimal_font_size
        )
        self.canvas_size_wh = canvas_size_wh

    def SetComposeFunc(self, compose_func: Callable[[Frame, Frame], np.ndarray]):
        self.compose_func = compose_func
        self.optimal_font_size = None

    def SetInfoProvideFunc(self, info_provide_func: Callable[[Frame, Frame], int]):
        self.info_provide_func = info_provide_func

    def _compose_overlay_text(self, info_text, merged_frame: Image.Image):

        img = merged_frame
        img_draw = ImageDraw.Draw(img, mode="RGB")
        text_w, text_h = self.font.getsize_multiline(info_text)
        possible_xy_size = (
            max(merged_frame.size[0] - text_w + 1, 1),
            max(merged_frame.size[1] - text_h + 1, 1),
        )
        final_xy_pos = (
            int(possible_xy_size[0] * self.font_config.location[1]),
            int(possible_xy_size[1] * self.font_config.location[0]),
        )

        if self.font_config.location[1] < 0.25:
            align = "left"
        elif self.font_config.location[1] > 0.75:
            align = "right"
        else:
            align = "center"
        img_draw.multiline_text(
            final_xy_pos,
            info_text,
            font=self.font,
            align=align,
            fill=self.font_config.color,
        )
        return img

    def HandleResize(self, canvas_size_wh):
        self.optimal_font_size = None

    def Compose(self, left_frame: Frame, right_frame: Frame):
        left_delta = left_frame[1]
        left_frame, right_frame = _check_frame_pair_is_correct(
            left_frame[0], right_frame[0] if right_frame is not None else None
        )
        combined_frame = self.compose_func(left_frame, right_frame)
        combined_frame = Image.fromarray(combined_frame)
        resize_coeff = min(
            self.canvas_size_wh[0] / combined_frame.width,
            self.canvas_size_wh[1] / combined_frame.height,
        )
        combined_frame = combined_frame.resize(
            size=(
                int(combined_frame.width * resize_coeff),
                int(combined_frame.height * resize_coeff),
            ),
            resample=Image.NEAREST,
        )
        info_to_display = self.info_provide_func(left_frame, right_frame)
        final_frame = self._compose_overlay_text(info_to_display, combined_frame)
        return final_frame, left_delta
