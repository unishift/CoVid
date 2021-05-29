import multiprocessing
import threading
from multiprocessing import Queue
from queue import Empty

import ffms2
import pathlib

from PIL import Image

import compose
from metrics import VQMTMetrics

from typing import Union, NamedTuple, Tuple, Callable, List

main_thread = threading.current_thread()


def _clamp(x, left, right):
    return max(left, min(x, right))


def dummy_func(*args):
    return args


def true_func(*args):
    return True


class VideoOpenException(BaseException):
    pass


class PlaybackPosition:
    def __init__(self, length, start_pos=0):
        self.length = length
        self.next_frame_idx = 0
        self.set_playback_frame_position(start_pos)

    def set_playback_frame_position(self, new_frame_idx: int):
        self.next_frame_idx = _clamp(new_frame_idx, 0, self.length - 1)

    def shift_playback_frame_position(self, delta: int):
        self.next_frame_idx = _clamp(self.next_frame_idx + delta, 0, self.length - 1)

    def is_end(self):
        return self.get_length() == self.get_playback_frame_position() + 1

    def get_length(self):
        return self.length

    def get_playback_frame_position(self):
        return self.next_frame_idx


class FfmsReader:
    def __init__(self, video_path: Union[str, pathlib.Path]):
        self.indexer = ffms2.Indexer(str(video_path))  # TODO throw error of our type
        self.index = self.indexer.do_indexing2()
        self.track_number = self.index.get_first_indexed_track_of_type(
            ffms2.FFMS_TYPE_VIDEO
        )
        self.vsource = ffms2.VideoSource(str(video_path), self.track_number, self.index)
        self.vsource.set_output_format(
            [ffms2.get_pix_fmt("rgb24")], resizer=ffms2.FFMS_RESIZER_FAST_BILINEAR
        )
        self.length = self.vsource.properties.NumFrames

        frame = self.vsource.get_frame(0)
        self.enc_width = frame.EncodedWidth
        self.enc_height = frame.EncodedHeight

    def get_length(self):
        return self.length

    def update_video_size(self, canvas_size_wh, width_multiplier=1.0):
        """Updates internal FFMS scaling method

        Args:
            canvas_size_wh: target (width, height)
            width_multiplier: 0.5 for side-by-side view, otherwise 1.0

        Returns:

        """
        resize_coeff = min(
            canvas_size_wh[0] * width_multiplier / self.enc_width,
            canvas_size_wh[1] / self.enc_height,
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

    def read_frame(self, frame_idx, canvas_size_wh):
        """Reads current frame and calculates timestamp delta

        Args:
            frame_idx: index of frame to read
            canvas_size_wh: canvas size. Not used, but is important for caching purposes (invalidates cache on canvas size change)

        Returns: frame, time_delta

        """
        frame = self.vsource.get_frame(frame_idx)
        width = frame.ScaledWidth or frame.EncodedWidth
        height = frame.ScaledHeight or frame.EncodedHeight
        next_frame_idx = _clamp(frame_idx + 1, 0, self.length - 1)
        frame_info_list = self.vsource.track.frame_info_list
        this_frame_delta = (
            frame_info_list[next_frame_idx].PTS - frame_info_list[frame_idx].PTS
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
        return array, this_frame_delta


class TaskExecuteFlags(NamedTuple):
    skip_to_last: bool  # ignore all except for the last task with this name
    priority: int  # among such tasks, highest priority one will be executed first


class SingleReaderProxy:
    def __init__(
        self, video_path: Union[str, pathlib.Path], in_queue: Queue, out_queue: Queue
    ):
        self.video_path = video_path
        self.in_queue = in_queue
        self.out_queue = out_queue

    def work_cycle(self):
        """Enter working cycle, receiving queries in self.in_queue and sending output
         in self.out_queue

        Returns:

        """
        try:
            reader = FfmsReader(self.video_path)
        except Exception as e:  # TODO catch our error
            self.out_queue.put((None, (self.video_path,), e))
            return
        while True:
            query = self.in_queue.get(block=True)
            cmd, args = query
            try:
                result = getattr(reader, cmd)(*args)
                self.out_queue.put((cmd, args, result))
            except Exception as e:
                self.out_queue.put((cmd, args, e))


def spawn_async_reader(
    video_path: Union[str, pathlib.Path], in_queue: Queue, out_queue: Queue
):
    """Stub function to be used from Process().start

    Args:
        video_path: Path to video to read
        in_queue: Input queue
        out_queue: Output queue

    Returns:

    """
    reader = SingleReaderProxy(video_path, in_queue, out_queue)
    reader.work_cycle()


class ProcessWrapper:
    def __init__(
        self, process: multiprocessing.Process, in_queue: Queue, out_queue: Queue
    ):
        self.process = process
        self.in_queue = in_queue
        self.out_queue = out_queue

    def execute(self, cmd, args):
        self.in_queue.put((cmd, args))

    def wait_for_execution(self):
        while True:
            try:
                ans = self.out_queue.get(block=True, timeout=1)
                return ans
            except Empty:
                if main_thread.is_alive() and self.process.is_alive():
                    continue
                else:
                    break

    def start(self):
        self.process.start()

    def end(self):
        self.process.kill()
        self.in_queue.close()
        self.out_queue.close()


class ProxyReaderPairWrapper:
    def __init__(
        self,
        video_path_1: Union[str, pathlib.Path, None],
        video_path_2: Union[str, pathlib.Path, None],
        in_queue: Queue,
        out_queue: Queue,
    ):
        self.left_process = None
        self.right_process = None

        self.in_queue = in_queue
        self.out_queue = out_queue

        self.reconfigure_paths(video_path_1, video_path_2, False)

        self.last_commands = {}

    def _local_exec(self, cmd, args_1, args_2, combine):
        for proc, arg in ((self.left_process, args_1), (self.right_process, args_2)):
            if proc is not None:
                proc.execute(cmd, arg)

        outs = []
        has_errors = False
        for proc in (self.left_process, self.right_process):
            if proc is not None:
                ans = proc.wait_for_execution()
                outs.append(ans[2])
                if isinstance(ans[2], BaseException):
                    has_errors = True
            else:
                outs.append(None)
        if combine is None or has_errors:
            return outs
        elif isinstance(combine, dict):
            ans = compose.Composer(**combine).compose(*outs)
            return ans

    def execute(self, cmd: str, args_1: Tuple, args_2: Tuple, combine: Callable):
        """Send command for execution to two video readers. Wait for result,
        combine and send to out_queue

        Args:
            cmd: Command to call
            args_1: Args for the first reader
            args_2: Args for the second reader
            combine: Function

        Returns:

        """
        try:
            ans = self._local_exec(cmd, args_1, args_2, combine)
            self.out_queue.put((cmd, (args_1, args_2), ans))
        except Exception as e:
            self.out_queue.put((cmd, (args_1, args_2), [e, None]))

    def reconfigure_paths(self, video_path_1, video_path_2, return_length=True):
        """Create readers from scratch, optionally reporting their lengths

        Args:
            video_path_1: Path to the left video
            video_path_2: Path to the right video
            return_length: Whether to put get_length result in
                self.out_queue

        Returns:

        """
        if self.left_process is not None:
            self.left_process.end()
            self.left_process = None
        if self.right_process is not None:
            self.right_process.end()
            self.right_process = None

        if video_path_1 is not None:
            q1, q2 = Queue(), Queue()
            left_process = multiprocessing.Process(
                target=spawn_async_reader, args=(video_path_1, q1, q2)
            )
            self.left_process = ProcessWrapper(left_process, q1, q2)
            self.left_process.start()

        if video_path_2 is not None:
            q3, q4 = Queue(), Queue()
            right_process = multiprocessing.Process(
                target=spawn_async_reader, args=(video_path_2, q3, q4)
            )
            self.right_process = ProcessWrapper(right_process, q3, q4)
            self.right_process.start()

        status = self._local_exec("get_length", (), (), None)
        if isinstance(status[0], BaseException):
            self.left_process.end()
            self.left_process = None
        if isinstance(status[1], BaseException):
            self.right_process.end()
            self.right_process = None
        if return_length:
            self.out_queue.put(("get_length", ((), ()), status))

    def work_cycle(self):
        """Enter working cycle, receiving queries in self.in_queue and sending output
         in self.out_queue

        Returns:

        """
        need_block = True
        while True:
            try:
                query = self.in_queue.get(block=need_block, timeout=1)
            except Empty:
                if need_block:
                    if main_thread.is_alive():
                        continue
                    else:
                        break
                if len(self.last_commands) > 0:
                    last_items = list(self.last_commands.items())
                    last_items.sort(key=lambda x: x[1][0], reverse=True)
                    cmd, (priority, args, combine) = last_items[0]
                    self.execute(cmd, args[0], args[1], combine)
                    del self.last_commands[cmd]
                if len(self.last_commands) == 0:
                    need_block = True
                continue

            need_block = False
            cmd, args, flags, combine = query
            cmd: str
            flags: TaskExecuteFlags
            if cmd == "_reconfigure":
                self.reconfigure_paths(*args)
            else:
                if flags.skip_to_last:
                    self.last_commands[cmd] = (flags.priority, args, combine)
                else:
                    self.execute(cmd, args[0], args[1], combine)


def spawn_pairs_reader(
    video_path_1: Union[str, pathlib.Path, None],
    video_path_2: Union[str, pathlib.Path, None],
    in_queue: Queue,
    out_queue: Queue,
):
    """Stub function to be used in Process()

    Args:
        video_path_1: Path to first video
        video_path_2: Path to second video
        in_queue: Input queue
        out_queue: Output queue

    Returns:

    """
    reader = ProxyReaderPairWrapper(video_path_1, video_path_2, in_queue, out_queue)
    reader.work_cycle()


class NonBlockingPairReader:
    def __init__(self, composer_type: str):
        """
        Args:
            composer_type: "split", "sbs" or "chess" - what composer
                type to use
        """
        self.in_queue = Queue()
        self.out_queue = Queue()
        self.last_input = {}
        self.last_cmd_data = {}
        self.left_pos: PlaybackPosition = None
        self.right_pos: PlaybackPosition = None
        self.left_file: str = None
        self.right_file: str = None
        self.left_metrics = VQMTMetrics()
        self.right_metrics = VQMTMetrics()
        self.composer_type = composer_type
        self.sample_text = "PSNR=34.57890123\nSSIM=0.99987123"
        self.font_config: compose.FontConfig = None
        self.reader = multiprocessing.Process(
            target=spawn_pairs_reader, args=(None, None, self.in_queue, self.out_queue)
        )
        self.metrics = []
        self.reader.start()

    def create_left_reader(self, new_file: Union[str, pathlib.Path]):
        self.left_file = str(new_file)
        self._recreate_readers()

    def create_right_reader(self, new_file: Union[str, pathlib.Path]):
        self.right_file = str(new_file)
        self._recreate_readers()

    def _video_to_metrics_path(self, video_path: str):
        return pathlib.Path(video_path).with_suffix(".json")  # todo regexp

    def _recreate_readers(self):
        if "get_length" in self.last_cmd_data:
            del self.last_cmd_data["get_length"]
        self._async_call(
            "_reconfigure",
            TaskExecuteFlags(skip_to_last=False, priority=0),
            args=(self.left_file, self.right_file),
            combine=None,
        )
        while "get_length" not in self.last_cmd_data:
            self._read_all_responses(True, 5)
        readers_lengths = self.last_cmd_data["get_length"][0]
        if isinstance(readers_lengths[0], BaseException):
            left_file = self.left_file
            self.left_file = None
            self.left_pos = None
            raise AttributeError(f"Error while opening {left_file}")
        if isinstance(readers_lengths[1], BaseException):
            right_file = self.right_file
            self.right_file = None
            self.right_pos = None
            raise AttributeError(f"Error while opening {right_file}")
        if readers_lengths[0] is not None:
            self.left_pos = PlaybackPosition(readers_lengths[0])
        else:
            self.left_pos = None

        if readers_lengths[1] is not None:
            self.right_pos = PlaybackPosition(readers_lengths[1])
        else:
            self.right_pos = None

        if self.left_file:
            self.left_metrics.load(self._video_to_metrics_path(self.left_file))
        if self.right_file:
            self.right_metrics.load(self._video_to_metrics_path(self.right_file))

    def _read_all_responses(self, wait_for_first=False, first_timeout=0.5):
        while True:
            try:
                cmd, args, result = self.out_queue.get(
                    block=wait_for_first, timeout=first_timeout
                )
                wait_for_first = False
                self.last_cmd_data[cmd] = (result, args)
            except Empty:
                break

    def _async_call(self, cmd, flags, args, combine):
        self.last_input[cmd] = args
        self.in_queue.put((cmd, args, flags, combine))

    def on_index_update(self, canvas_size_wh=None):
        """Notify backend that the reading position has been updated
        (start prefetching current frame)

        Args:
            canvas_size_wh: size of the canvas of the main window

        Returns:

        """
        self.get_next_frame(update_frame_idx=False, canvas_size_wh=canvas_size_wh)

    def has_no_tasks(self) -> bool:
        """Checks whether backend has any unfinished tasks
        (i.e. frame decoding or resize).

        Returns:
            True if backend has unfinished tasks
        """
        for key in self.last_cmd_data:
            if (
                key in self.last_input
                and self.last_cmd_data[key][1] != self.last_input[key]
            ):
                return False
        return True

    def read_current_frame(
        self, canvas_size_wh: Tuple[int, int]
    ) -> Tuple[Image.Image, float]:
        """Queues current frame for decoding and returns latest decoded frame.
        Blocks on the very first call

        Args:
            canvas_size_wh: size of the canvas of the main window

        Returns:
            Pair of image and timestamp difference (in msec)
        to the next frame
        """
        left_idx = None if self.left_pos is None else self.left_pos.next_frame_idx
        right_idx = None if self.right_pos is None else self.right_pos.next_frame_idx
        self._async_call(
            "read_frame",
            TaskExecuteFlags(skip_to_last=True, priority=0),
            ((left_idx, canvas_size_wh), (right_idx, canvas_size_wh)),
            {
                "compose_type": self.composer_type,
                "canvas_size_wh": canvas_size_wh,
                "font_config": self.font_config,
                "metrics": self.get_metrics(left_idx, right_idx),
            },
        )
        self._read_all_responses(False)
        if "read_frame" not in self.last_cmd_data:
            for i in range(5):
                if "read_frame" not in self.last_cmd_data:
                    self._read_all_responses(True)
                else:
                    return self.last_cmd_data["read_frame"][0]
            raise AttributeError("Wait for the first frame failed several times")
        return self.last_cmd_data["read_frame"][0]

    def _is_last_index_valid(self):
        last_index = self.last_input["read_frame"]
        return last_index == (
            (self.left_pos.next_frame_idx if self.left_pos else None,),
            (self.right_pos.next_frame_idx if self.right_pos else None,),
        )

    def get_next_frame(self, update_frame_idx=True, canvas_size_wh=None):
        """Queues current frame for decoding and returns latest decoded frame.
        Blocks on the very first call.
        Tries not to ask for redundant decoding of the current frame several times

        Args:
            update_frame_idx: Whether to update current frame position
                or not
            canvas_size_wh: Size of the canvas of the main window

        Returns:
            Pair of image and timestamp difference to the next frame
        """
        if (
            update_frame_idx
            or "read_frame" not in self.last_cmd_data
            or not self._is_last_index_valid()
        ):
            array, this_frame_delta = self.read_current_frame(canvas_size_wh)
            if update_frame_idx:
                self.left_pos.shift_playback_frame_position(1)
                self.right_pos.shift_playback_frame_position(1)
        else:
            array, this_frame_delta = self.repeat_last_frame()

        return array, this_frame_delta

    def update_video_size(self, canvas_size_wh: Tuple[int, int]):
        """Updates backend decoder's output video size according to the canvas size

        Args:
            canvas_size_wh: Size of the canvas of the main window

        Returns:

        """
        self.font_config = compose.FontConfig(canvas_size_wh, self.sample_text)
        width_multiplier = 0.5 if self.composer_type == "sbs" else 1.0
        self._async_call(
            "update_video_size",
            TaskExecuteFlags(skip_to_last=True, priority=1),
            ((canvas_size_wh, width_multiplier), (canvas_size_wh, width_multiplier)),
            None,
        )

    def repeat_last_frame(self) -> Tuple[Image.Image, float]:
        """Function to return latest decoded frame one more time

        Returns:
            Pair of image and timestamp difference (in msec) to the next
            frame
        """
        assert (
            "read_frame" in self.last_cmd_data
        ), "Call to RepeatLastFrame, but it is None"
        self._read_all_responses(False)
        return self.last_cmd_data["read_frame"][0]

    def close(self):
        self.left_file = None
        self.right_file = None
        self.reader.kill()

    def get_metrics(self, left_idx: int, right_idx: int):
        """
        Args:
            left_idx: left frame number
            right_idx: right frame number

        Returns: list of (metric label, (left score, right score))
        """
        if not self.metrics:
            return []
        labels, requested_metrics = zip(*self.metrics)
        left_metrics = self.left_metrics.query(left_idx, requested_metrics)
        right_metrics = self.right_metrics.query(right_idx, requested_metrics)
        return list(zip(labels, zip(left_metrics, right_metrics)))
