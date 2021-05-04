import numpy as np

from typing import Callable, Tuple
from PIL import Image, ImageDraw, ImageFont

Frame = np.ndarray


class FontConfig:
    def __init__(
        self,
        font: str = "arial",
        location: Tuple[float, float] = (0.0, 1.0),
        color: Tuple[int, int, int] = (255, 255, 0),
        rel_max_size: Tuple[float, float] = (0.5, 0.75),
    ):
        self.font = font
        self.location = location
        self.color = color
        self.rel_max_size = rel_max_size


def _check_frame_pair_is_correct(left_frame: Frame, right_frame: Frame):
    assert left_frame.shape == right_frame.shape, (
        f"Frame pair is expected to have same shape, but found "
        f"{left_frame.shape} vs {right_frame.shape}"
    )
    assert (
        len(left_frame.shape) == 3 and left_frame.shape[-1] == 3
    ), f"Frames are expected to be 3-channel colored images"


def ComposeVerticalSplit(
    left_frame: Frame, right_frame: Frame, left_fraction: float = 0.50
):
    _check_frame_pair_is_correct(left_frame, right_frame)
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
    def __init__(
        self,
        compose_func: Callable[[Frame, Frame], Frame],
        info_provide_func: Callable[[Frame, Frame], str],
        font_config: FontConfig,
    ):
        self.compose_func = compose_func
        self.info_provide_func = info_provide_func
        self.font_config = font_config
        self.optimal_font_size = None
        self.font = None

    def SetComposeFunc(self, compose_func: Callable[[Frame, Frame], np.ndarray]):
        self.compose_func = compose_func
        self.optimal_font_size = None

    def SetInfoProvideFunc(self, info_provide_func: Callable[[Frame, Frame], int]):
        self.info_provide_func = info_provide_func

    def SetFontConfig(self, font_config: FontConfig):
        self.font_config = font_config
        self.optimal_font_size = None

    def _determine_optimal_font_size(
        self, sample_text: str, canvas_shape: Tuple[int, int]
    ):
        max_font_size = 100
        desired_h = canvas_shape[0] * self.font_config.rel_max_size[0]
        desired_w = canvas_shape[1] * self.font_config.rel_max_size[1]
        for font_size in range(1, max_font_size + 1):
            font = ImageFont.truetype(self.font_config.font + ".ttf", size=font_size)
            w, h = font.getsize(sample_text)
            if w > desired_w or h > desired_h:
                self.optimal_font_size = font_size - 1
                self.font = ImageFont.truetype(
                    self.font_config.font + ".ttf", size=self.optimal_font_size
                )
                return
        self.optimal_font_size = max_font_size
        self.font = ImageFont.truetype(
            self.font_config.font + ".ttf", size=self.optimal_font_size
        )

    def _compose_overlay_text(self, info_text, merged_frame: Image.Image):
        if self.optimal_font_size is None:
            self._determine_optimal_font_size(
                info_text, canvas_shape=tuple(merged_frame.size[::-1])
            )

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

    def Compose(self, left_frame: Frame, right_frame: Frame, canvas_size_wh=None):
        _check_frame_pair_is_correct(left_frame, right_frame)
        combined_frame = self.compose_func(left_frame, right_frame)
        combined_frame = Image.fromarray(combined_frame)
        resize_coeff = min(
            canvas_size_wh[0] / combined_frame.width,
            canvas_size_wh[1] / combined_frame.height,
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
        return final_frame
