import multiprocessing
import threading
from multiprocessing import Queue
from queue import Empty

import ffms2
import pathlib
import compose

from typing import Union, NamedTuple

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
        self.SetPlaybackFramePosition(start_pos)

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

        frame = self.vsource.get_frame(0)
        self.enc_width = frame.EncodedWidth
        self.enc_height = frame.EncodedHeight

    """
    def SetPlaybackFramePosition(self, new_frame_idx: int):
        self.next_frame_idx = _clamp(new_frame_idx, 0, self.length - 1)

    def ShiftPlaybackFramePosition(self, delta: int):
        self.next_frame_idx = _clamp(self.next_frame_idx + delta, 0, self.length - 1)

    def IsEnd(self):
        return self.GetLength() == self.GetPlaybackFramePosition() + 1


    def GetPlaybackFramePosition(self):
        return self.next_frame_idx
"""

    def GetLength(self):
        return self.length

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

    def ReadFrame(self, frame_idx, canvas_size_wh):
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
        try:
            reader = FfmsReader(self.video_path)
        except Exception as e:  # TODO catch our error
            self.out_queue.put(e)
        while True:
            query = self.in_queue.get(block=True)
            cmd, args = query
            if cmd == "_exit":
                break
            else:
                # print("doing things", cmd)
                result = getattr(reader, cmd)(*args)
                self.out_queue.put((cmd, args, result))


def spawn_async_reader(
    video_path: Union[str, pathlib.Path], in_queue: Queue, out_queue: Queue
):
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
        # print("ProcWrap execute", cmd)
        self.in_queue.put((cmd, args))

    def wait_for_execution(self):
        while True:
            try:
                ans = self.out_queue.get(block=True, timeout=1)
                return ans
            except Empty:
                if main_thread.is_alive():
                    continue
                else:
                    print("Exit!")
                    break

        # print("returning")

    def start(self):
        self.process.start()

    def end(self):
        self.process.kill()


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
        # print("_local_exec", cmd)
        for proc, arg in ((self.left_process, args_1), (self.right_process, args_2)):
            if proc is not None:
                proc.execute(cmd, arg)

        outs = []
        for proc in (self.left_process, self.right_process):
            if proc is not None:
                ans = proc.wait_for_execution()[2]
                # print("got ans from", cmd)
                outs.append(ans)
            else:
                outs.append(None)
        if combine is None:
            return outs
        elif isinstance(combine, dict):
            ans = compose.Composer(**combine).Compose(*outs)
            return ans

    def execute(self, cmd, args_1, args_2, combine):
        # print("execute", cmd)
        ans = self._local_exec(cmd, args_1, args_2, combine)
        self.out_queue.put((cmd, (args_1, args_2), ans))

    def reconfigure_paths(self, video_path_1, video_path_2, return_length=True):
        if self.left_process is not None:
            self.left_process.end()
            self.left_process = None
            self.left_reader = None
        if self.right_process is not None:
            self.right_process.end()
            self.right_process = None
            self.right_reader = None

        if video_path_1 is not None:
            self.left_reader = SingleReaderProxy(video_path_1, Queue(), Queue())
            q1, q2 = Queue(), Queue()
            left_process = multiprocessing.Process(
                target=spawn_async_reader, args=(video_path_1, q1, q2)
            )
            self.left_process = ProcessWrapper(left_process, q1, q2)
            self.left_process.start()

        if video_path_2 is not None:
            self.right_reader = SingleReaderProxy(video_path_2, Queue(), Queue())
            q3, q4 = Queue(), Queue()
            right_process = multiprocessing.Process(
                target=spawn_async_reader, args=(video_path_2, q3, q4)
            )
            self.right_process = ProcessWrapper(right_process, q3, q4)
            self.right_process.start()

        status = self._local_exec("GetLength", (), (), None)
        if isinstance(status[0], BaseException):
            self.left_reader = None
            self.left_process.end()
            self.left_process = None
        if isinstance(status[1], BaseException):
            self.right_reader = None
            self.right_process.end()
            self.right_process = None
        if return_length:
            self.out_queue.put(("GetLength", ((), ()), status))

    def work_cycle(self):
        need_block = True
        while True:
            try:
                query = self.in_queue.get(block=need_block, timeout=1)
                # print("Got!", query[0])
            except Empty:
                if need_block:
                    if main_thread.is_alive():
                        continue
                    else:
                        print("Exit!")
                        break
                if len(self.last_commands) > 0:
                    last_items = list(self.last_commands.items())
                    last_items.sort(key=lambda x: x[1][0], reverse=True)
                    cmd, (priority, args, combine) = last_items[0]
                    # print("exec", cmd)
                    if len(last_items) > 1:
                        pass
                        # print("Exec queue", [x[0] for x in last_items])
                    self.execute(cmd, args[0], args[1], combine)
                    del self.last_commands[cmd]
                if len(self.last_commands) == 0:
                    need_block = True
                continue

            need_block = False
            cmd, args, flags, combine = query
            cmd: str
            flags: TaskExecuteFlags
            if cmd == "_exit":
                break
            elif cmd == "_reconfigure":
                self.reconfigure_paths(*args)
            else:
                if flags.skip_to_last:
                    self.last_commands[cmd] = (flags.priority, args, combine)
                else:
                    # print("imm exec", cmd)
                    self.execute(cmd, args[0], args[1], combine)


def spawn_pairs_reader(
    video_path_1: Union[str, pathlib.Path, None],
    video_path_2: Union[str, pathlib.Path, None],
    in_queue: Queue,
    out_queue: Queue,
):
    reader = ProxyReaderPairWrapper(video_path_1, video_path_2, in_queue, out_queue)
    reader.work_cycle()


class NonBlockingPairReader:
    def __init__(self, composer_type):
        self.in_queue = Queue()
        self.out_queue = Queue()
        self.last_input = {}
        # self._async_call('GetLength', TaskExecuteFlags(skip_to_last=False, priority=0))
        # _, _, self.length = self.out_queue.get(block=True)  # Very nonblocking
        self.last_cmd_data = {}
        self.left_pos: PlaybackPosition = None
        self.right_pos: PlaybackPosition = None
        self.left_file: str = None
        self.right_file: str = None
        self.composer_type = composer_type
        self.sample_text = "PSNR=34.57890123\nSSIM=0.99987123"
        self.font_config: compose.FontConfig = None
        self.reader = multiprocessing.Process(
            target=spawn_pairs_reader, args=(None, None, self.in_queue, self.out_queue)
        )
        self.reader.start()

    def CreateLeftReader(self, new_file):
        self.left_file = new_file
        self._recreate_readers()

    def CreateRightReader(self, new_file):
        self.right_file = new_file
        self._recreate_readers()

    def _recreate_readers(self):
        # print("_recreate_readers")
        if "GetLength" in self.last_cmd_data:
            del self.last_cmd_data["GetLength"]
        self._async_call(
            "_reconfigure",
            TaskExecuteFlags(skip_to_last=False, priority=0),
            args=(self.left_file, self.right_file),
            combine=None,
        )
        while "GetLength" not in self.last_cmd_data:
            self._read_all_responses(True, 5)
        readers_lengths = self.last_cmd_data["GetLength"][0]
        if isinstance(readers_lengths[0], BaseException):
            raise AttributeError(f"Error while opening {self.left_file}")
        if isinstance(readers_lengths[1], BaseException):
            raise AttributeError(f"Error while opening {self.right_file}")
        # print("lengths", readers_lengths)
        if readers_lengths[0] is not None:
            self.left_pos = PlaybackPosition(readers_lengths[0])
        else:
            self.left_pos = None

        if readers_lengths[1] is not None:
            self.right_pos = PlaybackPosition(readers_lengths[1])
        else:
            self.right_pos = None

    def _read_all_responses(self, wait_for_first=False, first_timeout=0.5):
        while True:
            try:
                cmd, args, result = self.out_queue.get(
                    block=wait_for_first, timeout=first_timeout
                )
                wait_for_first = False
                self.last_cmd_data[cmd] = (result, args)
                if cmd == "ReadFrame":
                    pass
                    # print("Finished reading", cmd, args)
                else:
                    pass
                    # print("Finished reading", cmd)
            except Empty:
                break

    def _async_call(self, cmd, flags, args, combine):
        # print("top-level call", cmd)
        self.last_input[cmd] = args
        self.in_queue.put((cmd, args, flags, combine))

    def OnIndexUpdate(self, canvas_size_wh=None):
        self.GetNextFrame(update_frame_idx=False, canvas_size_wh=canvas_size_wh)

    def HasNoTasks(self):
        for key in self.last_cmd_data:
            if key in self.last_input:
                pass
                # print("checking tasks...", key, self.last_cmd_data[key][1], self.last_input[key])
            if (
                key in self.last_input
                and self.last_cmd_data[key][1] != self.last_input[key]
            ):
                # print("We have tasks")
                return False
        # print("No tasks!")
        return True

    def ReadCurrentFrame(self, canvas_size_wh):
        left_idx = None if self.left_pos is None else self.left_pos.next_frame_idx
        right_idx = None if self.right_pos is None else self.right_pos.next_frame_idx
        # print("Asked for frame", left_idx, right_idx, canvas_size_wh)
        self._async_call(
            "ReadFrame",
            TaskExecuteFlags(skip_to_last=True, priority=0),
            ((left_idx, canvas_size_wh), (right_idx, canvas_size_wh)),
            {
                "compose_type": self.composer_type,
                "canvas_size_wh": canvas_size_wh,
                "font_config": self.font_config,
            },
        )
        self._read_all_responses(False)
        if "ReadFrame" not in self.last_cmd_data:
            for i in range(5):
                if "ReadFrame" not in self.last_cmd_data:
                    self._read_all_responses(True)
                else:
                    return self.last_cmd_data["ReadFrame"][0]
            raise AttributeError("Wait for the first frame failed several times")
        return self.last_cmd_data["ReadFrame"][0]

    def _is_last_index_valid(self):
        last_index = self.last_input["ReadFrame"]
        return last_index == (
            (self.left_pos.next_frame_idx if self.left_pos else None,),
            (self.right_pos.next_frame_idx if self.right_pos else None,),
        )

    def GetNextFrame(self, update_frame_idx=True, canvas_size_wh=None):
        if (
            update_frame_idx
            or "ReadFrame" not in self.last_cmd_data
            or not self._is_last_index_valid()
        ):
            array, this_frame_delta = self.ReadCurrentFrame(canvas_size_wh)
            if update_frame_idx:
                self.left_pos.ShiftPlaybackFramePosition(1)
                self.right_pos.ShiftPlaybackFramePosition(1)
        else:
            array, this_frame_delta = self.RepeatLastFrame()

        return array, this_frame_delta

    def UpdateVideoSize(self, canvas_size_wh):
        self.font_config = compose.FontConfig(canvas_size_wh, self.sample_text)
        self._async_call(
            "UpdateVideoSize",
            TaskExecuteFlags(skip_to_last=True, priority=1),
            ((canvas_size_wh,), (canvas_size_wh,)),
            None,
        )

    def RepeatLastFrame(self):
        assert (
            "ReadFrame" in self.last_cmd_data
        ), "Call to RepeatLastFrame, but it is None"
        # print("Repeating last frame")
        self._read_all_responses(False)
        return self.last_cmd_data["ReadFrame"][0]
