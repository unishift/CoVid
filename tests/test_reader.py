import os

import PIL
import numpy as np

from covid.metrics import VQMTMetrics
from covid.video_reader import PlaybackPosition, FfmsReader, NonBlockingPairReader


def test_playback():
    pos = PlaybackPosition(10, 100)
    assert pos.get_playback_frame_position() == 9

    pos.shift_playback_frame_position(-100)
    assert pos.get_playback_frame_position() == 0

    pos.shift_playback_frame_position(3)
    assert pos.get_playback_frame_position() == 3

    pos.set_playback_frame_position(10)
    assert pos.get_playback_frame_position() == 9


def test_video_reader():
    reader = FfmsReader("samples/foreman_crf30_short.mp4")

    assert (reader.get_length(), reader.enc_width, reader.enc_height) == (210, 352, 288)
    frame = reader.read_frame(0, None)
    assert frame[0].shape == (reader.enc_height, reader.enc_width, 3)
    reader.update_video_size((600, 600))
    assert max(reader.read_frame(0, None)[0].shape) == 600


def test_threaded():
    with NonBlockingPairReader("sbs") as main_thread:
        main_thread.create_left_reader("samples/foreman_crf30_short.mp4")
        main_thread.update_video_size((600, 600))
        frame, delta = main_thread.get_next_frame(False, (600, 600))
        print(frame, delta)
        assert isinstance(frame, PIL.Image.Image)
        frame = np.array(frame)
        assert (frame[:, int(frame.shape[1] * 0.8):, :]).max() < 0.01

        main_thread.composer_type = "chess"
        main_thread.create_right_reader("samples/foreman_crf40_short.mp4")
        main_thread.update_video_size((800, 800))
        del main_thread.last_cmd_data["read_frame"]
        frame, delta = main_thread.get_next_frame(False, (800, 800))
        main_thread.composer_type = "split"
        del main_thread.last_cmd_data["read_frame"]
        frame, delta = main_thread.get_next_frame(False, (800, 800))
        assert isinstance(frame, PIL.Image.Image)
        frame = np.array(frame)
        assert (frame[:, int(frame.shape[1] * 0.8):, :]).max() > 0.01

        main_thread.metrics = [
            ("PSNR, Y", VQMTMetrics.PSNR_Y)
        ]
        metrics = main_thread.get_metrics(0, 0)[0][1]
        assert 13 < metrics[0] < metrics[1] < 14
        assert main_thread.has_no_tasks()
    #main_thread.close()

if __name__ == "__main__":
    test_threaded()