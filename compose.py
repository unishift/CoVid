import os
from typing import Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

Frame = np.ndarray


class FontConfig:
    def __init__(
        self,
        canvas_size_wh: Tuple[int, int],
        sample_text: str,
        font: str = os.path.join(
            os.path.dirname(__file__), "resources", "OpenSans-Regular"
        ),
        location: Tuple[float, float] = (0.0, 1.0),
        color: Tuple[int, int, int] = (255, 255, 0),
        rel_max_size: Tuple[float, float] = (0.5, 0.75),
    ):
        """Font configuration

        Args:
            canvas_size_wh: Size of the canvas on the main window
            sample_text: Text used to calculate font size
            font: ttf name (for example, "arial")
            location: (y, x) from 0 to 1 each: relative text position
            color: font color
            rel_max_size: fraction of the full frame to be filled with
                text
        (0 == left/top, 1 == bottom/right)
        (used in auto font size calculation)
        """
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


def compose_vertical_split(
    left_frame: Frame, right_frame: Frame, left_fraction: float = 0.50
):
    """Perform composition using vertical split method

    Args:
        left_frame
        right_frame
        left_fraction: Fraction of left frame used in composition
    (remainder is the right frame)

    Returns:

    """
    left_frame, right_frame = _check_frame_pair_is_correct(left_frame, right_frame)
    merged_frame = np.copy(right_frame)
    threshold = int(left_fraction * left_frame.shape[1])
    merged_frame[:, :threshold] = left_frame[:, :threshold]
    return merged_frame


def compose_chess_pattern(
    left_frame: Frame, right_frame: Frame, cell_size: float = 0.25
):
    """Perform composition using chess method

    Args:
        left_frame: top left tile
        right_frame
        cell_size: Size of each cell relative to frame height

    Returns:

    """
    left_frame, right_frame = _check_frame_pair_is_correct(left_frame, right_frame)
    h, w, _ = left_frame.shape
    cell_width = int(h * cell_size)
    unit = np.repeat(
        np.repeat([[1, 0], [0, 1]], cell_width, axis=0), cell_width, axis=1
    )
    chess_pattern = np.tile(unit, (h // cell_width + 1, w // cell_width + 1))[
        :h, :w, np.newaxis
    ]
    frame = np.where(chess_pattern, left_frame, right_frame)
    return frame


def compose_side_by_side(left_frame: Frame, right_frame: Frame):
    _check_frame_pair_is_correct(left_frame, right_frame)
    return np.hstack((left_frame, right_frame))


class Composer:
    def __init__(
        self,
        compose_type: str,
        font_config: FontConfig,
        metrics: dict,
        canvas_size_wh=None,
    ):
        if compose_type == "split":
            self.compose_func = compose_vertical_split
        elif compose_type == "sbs":
            self.compose_func = compose_side_by_side
        elif compose_type == "chess":
            self.compose_func = compose_chess_pattern
        else:
            raise NotImplementedError("Unknown backend!")
        self.font_config = font_config
        self.font = ImageFont.truetype(
            self.font_config.font + ".ttf", size=self.font_config.optimal_font_size
        )
        self.canvas_size_wh = canvas_size_wh
        self.metrics = metrics

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

    def format_text(self):
        rows = []
        for label, values in self.metrics:
            left, right = values
            left = "None" if left is None else f"{left:.03f}"
            right = "None" if right is None else f"{right:.03f}"
            rows.append(f"{label}: {left} vs. {right}")
        return "\n".join(rows)

    def compose(
        self, left_frame: Frame, right_frame: Frame
    ) -> Tuple[Image.Image, float]:
        """Performs frame composition, merging two frames and writing text

        Args:
            left_frame
            right_frame

        Returns:
            Tuple of Image and left frame delta timestamp (in msec)
        to the next frame
        """
        left_delta = left_frame[1] if left_frame is not None else 1000 / 24.0
        left_frame, right_frame = _check_frame_pair_is_correct(
            left_frame[0] if left_frame is not None else None,
            right_frame[0] if right_frame is not None else None,
        )
        combined_frame = self.compose_func(left_frame, right_frame)
        combined_frame = Image.fromarray(combined_frame)

        info_to_display = self.format_text()
        final_frame = self._compose_overlay_text(info_to_display, combined_frame)
        return final_frame, left_delta
