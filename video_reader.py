import ffms2
import pathlib

from typing import Union


def _clamp(x, left, right):
    return max(left, min(x, right))


class VideoOpenException(BaseException):
    pass


class FfmsReader:
    def __init__(self, video_path: Union[str, pathlib.Path]):
        self.indexer = ffms2.Indexer(str(video_path))  # TODO throw error of our type
        self.index = self.indexer.do_indexing2()
        self.track_number = self.index.get_first_indexed_track_of_type(
            ffms2.FFMS_TYPE_VIDEO
        )
        self.vsource = ffms2.VideoSource(str(video_path), self.track_number, self.index)
        self.vsource.set_output_format([ffms2.get_pix_fmt("rgb24")])
        self.length = self.vsource.properties.NumFrames
        self.next_frame_idx = 0

        frame = self.vsource.get_frame(0)
        self.enc_width = frame.EncodedWidth
        self.enc_height = frame.EncodedHeight

    def SetPlaybackFramePosition(self, new_frame_idx: int):
        self.next_frame_idx = _clamp(new_frame_idx, 0, self.length - 1)

    def ShiftPlaybackFramePosition(self, delta: int):
        self.next_frame_idx = _clamp(self.next_frame_idx + delta, 0, self.length - 1)

    def IsEnd(self):
        return self.GetLength() == self.GetPlaybackFramePosition() + 1

    def GetLength(self):
        return self.length

    def GetPlaybackFramePosition(self):
        return self.next_frame_idx

    def UpdateVideoSize(self, canvas_size_wh):
        resize_coeff = min(
            canvas_size_wh[0] / self.enc_width, canvas_size_wh[1] / self.enc_height
        )
        new_shape = (
            int(self.enc_width * resize_coeff),
            int(self.enc_height * resize_coeff),
        )
        self.vsource.set_output_format(
            width=new_shape[0],
            height=new_shape[1],
            resizer=ffms2.FFMS_RESIZER_FAST_BILINEAR,
        )

    def GetNextFrame(self):
        frame = self.vsource.get_frame(self.next_frame_idx)
        width = frame.ScaledWidth or frame.EncodedWidth
        height = frame.ScaledHeight or frame.EncodedHeight
        after_next_frame_idx = _clamp(self.next_frame_idx + 1, 0, self.length - 1)
        frame_info_list = self.vsource.track.frame_info_list
        this_frame_delta = (
            frame_info_list[after_next_frame_idx].PTS
            - frame_info_list[self.next_frame_idx].PTS
        )
        time_base = self.vsource.track.time_base
        this_frame_delta *= time_base.numerator / time_base.denominator
        if this_frame_delta < 1e-3:
            this_frame_delta = 1 / 24
        array = (
            frame.planes[0]
            .reshape((height, frame.Linesize[0]))[:, 0 : (width * 3)]
            .reshape(height, width, 3)
        )
        self.next_frame_idx = after_next_frame_idx
        return array, this_frame_delta
