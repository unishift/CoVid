import os
import gettext
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from functools import partial

from PIL import ImageTk

from . import video_reader
from .metrics import VQMTMetrics

gettext.install("covid", os.path.dirname(__file__))


class Application(tk.Frame):
    """Sample tkinter application class"""

    def __init__(self, master=None, title="<application>", **kwargs):
        """Create root window with frame, tune weight and resize"""
        super().__init__(master, **kwargs)
        self.master.title(title)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.grid(sticky="NEWS")
        self.create_widgets()
        self.configure_widgets()

    def create_widgets(self):
        """Create all the widgets"""

    @staticmethod
    def make_flexible(grid):
        for column in range(grid.grid_size()[0]):
            grid.columnconfigure(column, weight=1)
        for row in range(grid.grid_size()[1]):
            grid.rowconfigure(row, weight=1)

    def configure_widgets(self):
        self.make_flexible(self)


class App(Application):
    def __init__(self, *args, **kwargs):
        super(App, self).__init__(*args, **kwargs)

        self.paused = True
        self.play_cycle_paused = True  # This can differ from paused when we
        # pause video and it needs to load several frames from async video reader
        self.last_image = None
        self.last_time = None
        self.resize_delay_counter = 0
        self.last_canvas_size = (self.C.winfo_width(), self.C.winfo_height())
        self.reader = video_reader.NonBlockingPairReader("split")
        self.master.protocol("WM_DELETE_WINDOW", self.handle_close)
        self.metrics = [
            ("PSNR, Y", (tk.BooleanVar(), VQMTMetrics.PSNR_Y)),
            ("SSIM, Y", (tk.BooleanVar(), VQMTMetrics.SSIM_Y)),
            ("NIQE, Y", (tk.BooleanVar(), VQMTMetrics.NIQE_Y)),
            ("VMAF v0.6.1, Y", (tk.BooleanVar(), VQMTMetrics.VMAF061_Y)),
        ]

        self.create_menu()

    def create_widgets(self):
        super().create_widgets()

        self.C = tk.Label(self)  # , background="gray75")
        self.C.grid(sticky="NEWS")
        self.controls = tk.Frame(self)
        self.controls.grid(sticky="EWS", row=1)

        self.back_fast = tk.Button(
            self.controls, text="<<", command=partial(self.scroll_both_videos, -10)
        )
        self.back_fast.grid(row=0, column=0, sticky="W")
        self.back = tk.Button(
            self.controls, text="<", command=partial(self.scroll_both_videos, -1)
        )
        self.back.grid(row=0, column=1, sticky="W")

        self.timeline = tk.Scale(
            self.controls,
            from_=0,
            to_=100,
            orient=tk.HORIZONTAL,
            command=self.handle_timeline_change,
        )
        self.timeline.grid(row=0, column=2, sticky="EW")

        self.forward = tk.Button(
            self.controls, text=">", command=partial(self.scroll_both_videos, 1)
        )
        self.forward.grid(row=0, column=3, sticky="E")
        self.forward_fast = tk.Button(
            self.controls, text=">>", command=partial(self.scroll_both_videos, 10)
        )
        self.forward_fast.grid(row=0, column=4, sticky="E")

        self.offset = tk.StringVar()
        self.offset.set("0")
        self.offset_box = tk.Spinbox(
            self.controls,
            from_=-100,
            to=100,
            textvariable=self.offset,
            command=self.handle_offset_change,
        )
        self.offset_box.grid(row=1, column=2)

        self.master.bind("<Configure>", self.handle_resize)
        self.master.bind("<space>", self.toggle_pause)
        # todo bind forwarding

    def configure_widgets(self):
        super().configure_widgets()
        self.rowconfigure(1, weight=0)  # fixed controls height
        self.controls.columnconfigure(2, weight=1)

    def _select_video_safe(self):
        file_name = filedialog.askopenfilename()
        if file_name == "":
            return None
        return file_name

    def _unbind_timeline_events(self):
        self.timeline.configure(command=None)
        self.offset_box.configure(command=None)

    def _bind_timeline_events(self):
        self.timeline.configure(command=self.handle_timeline_change)
        self.offset_box.configure(command=self.handle_offset_change)

    def _sync_progress_bar_with_videos(self):
        """Synchronizes timeline (pos, min/max) with current offset
        and videos scroll position

        Returns:

        """
        self._unbind_timeline_events()
        left_length = self.reader.left_pos.get_length()
        right_length = self.reader.right_pos.get_length()

        offset = int(self.offset.get())

        self.timeline.config(
            from_=max(-offset, 0), to=min(left_length - 1, right_length - 1 - offset)
        )

        self.timeline.set(self.reader.left_pos.get_playback_frame_position())
        self._bind_timeline_events()

    def _sync_video_with_offset(self):
        """Synchronizes videos with offset. At first it tries to shift
        right video forward, then it tries to shift left video backwards,
        at last it updates the offset if the two previous methods failed.
        It will always result in correct synchronous offset and timeline
        values, but each of them might be changed during this procedure

        Returns:

        """
        assert self.reader.left_pos is not None and self.reader.right_pos is not None
        self._unbind_timeline_events()
        current_delta = (
            self.reader.right_pos.get_playback_frame_position()
            - self.reader.left_pos.get_playback_frame_position()
        )
        desired_delta = int(self.offset.get())
        if (
            current_delta != desired_delta
        ):  # If we need to fix offset, at first we try to move right video
            self.reader.right_pos.shift_playback_frame_position(
                desired_delta - current_delta
            )
        current_delta = (
            self.reader.right_pos.get_playback_frame_position()
            - self.reader.left_pos.get_playback_frame_position()
        )
        if current_delta != desired_delta:  # If it's not enough, we move left video
            self.reader.left_pos.shift_playback_frame_position(
                -(desired_delta - current_delta)
            )
        current_delta = (
            self.reader.right_pos.get_playback_frame_position()
            - self.reader.left_pos.get_playback_frame_position()
        )
        if (
            current_delta != desired_delta
        ):  # Finally we understand that we can't fix offset and change the value back
            self.offset.set(str(current_delta))
        self.timeline.set(self.reader.left_pos.get_playback_frame_position())
        # Now we need to fix maximum progress_bar value
        # as the offset might have an impact on it
        self._bind_timeline_events()
        self._sync_progress_bar_with_videos()

    def _full_interface_sync(self):
        self._sync_video_with_offset()
        self._sync_progress_bar_with_videos()
        self.reader.on_index_update((self.C.winfo_width(), self.C.winfo_height()))

    def _videos_next_frame(self, update_frame_idx=True):
        """Draw next frame to canvas

        Args:
            update_frame_idx: Whether to update current frame position

        Returns:
            time delta (in msec) to the next frame
        (or 0 in cases when it's unavailable)
        """
        canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
        if self.reader.left_pos is None and self.reader.right_pos is None:
            return
        if (
            self.reader.left_pos is None
            or self.reader.right_pos is None
            or self.reader.left_pos.is_end()
            or self.reader.right_pos.is_end()
        ):
            update_frame_idx = False  # not playing forward

        frame, left_delta = self.reader.get_next_frame(update_frame_idx, canvas_size_wh)

        if update_frame_idx:
            self._sync_progress_bar_with_videos()

        if self.last_image is None or (
            frame.height != self.last_image.height()
            or frame.width != self.last_image.width()
        ):
            self.last_image = ImageTk.PhotoImage(frame)
            self.C.configure(image=self.last_image)
        else:
            self.last_image.paste(frame)
        return left_delta if update_frame_idx else None

    def _update_canvas_image(self):
        if self.play_cycle_paused:  # Otherwise will update itself in video play cycle
            self.video_playback_update()

    def scroll_both_videos(self, delta):
        if self.reader.left_pos is not None and self.reader.right_pos is not None:
            self.reader.left_pos.shift_playback_frame_position(delta)
            self.reader.right_pos.shift_playback_frame_position(delta)
            self._full_interface_sync()
            self._update_canvas_image()

    def handle_resize(self, event):
        canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
        if self.last_canvas_size != canvas_size_wh:
            self.last_canvas_size = canvas_size_wh
            self.reader.update_video_size(canvas_size_wh)
            self._update_canvas_image()

    def handle_close(self):
        self.reader.close()
        self.master.destroy()

    def toggle_pause(self, event):
        if self.paused:
            self._check_start_timer(0)
        else:
            self.paused = True

    def handle_offset_change(self):
        if self.reader.left_pos is not None and self.reader.right_pos is not None:
            self._full_interface_sync()
            self._update_canvas_image()

    def handle_timeline_change(self, event):
        if self.reader.left_pos is not None and self.reader.right_pos is not None:
            if event == str(self.reader.left_pos.get_playback_frame_position()):
                return
            self.reader.left_pos.set_playback_frame_position(self.timeline.get())
            self.reader.right_pos.set_playback_frame_position(
                self.timeline.get() + int(self.offset.get())
            )
            self._full_interface_sync()
            self._update_canvas_image()

    def video_playback_update(self):
        """Update function. Handles smooth pause
        (when we have unfinished background tasks,
        pause is not instant, but keeps everything in sync)

        Returns:

        """
        left_no_tasks = self.reader.left_pos is None or self.reader.has_no_tasks()
        right_no_tasks = self.reader.right_pos is None or self.reader.has_no_tasks()
        if self.paused and left_no_tasks and right_no_tasks:
            self.play_cycle_paused = True
            self._videos_next_frame(False)
            return
        next_update_time = 1000.0 / 24
        if (
            not self.paused
            and self.reader.left_pos is not None
            and self.reader.right_pos is not None
        ):
            self.last_time = time.perf_counter()
            left_delta = self._videos_next_frame()
            if left_delta is None:
                self.paused = True
            else:
                new_time = time.perf_counter()
                elapsed_time = (new_time - self.last_time) * 1000
                next_update_time = max((left_delta - elapsed_time), 0)
                # print(
                #     self.last_time, new_time, elapsed_time,
                #     left_delta, next_update_time
                # )
                self.last_time = new_time
        else:
            self._videos_next_frame(False)
        self.play_cycle_paused = False
        self.master.after(
            int(next_update_time), self.video_playback_update
        )  # TODO after() can't be reliably used for frame scheduling.
        # TODO Better write some compensation logic later for after()

    def _check_start_timer(self, delay):
        if (
            self.reader.left_pos is not None
            and self.reader.right_pos is not None
            and self.paused
        ):
            self.paused = False
            if self.play_cycle_paused:
                self.play_cycle_paused = False
                self.master.after(int(delay), self.video_playback_update)

    def _on_select_canvas_update(self, first_pos, second_pos):
        canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
        self.reader.update_video_size(canvas_size_wh)
        if first_pos is not None and second_pos is not None:
            self._full_interface_sync()
            self._check_start_timer(0)

    def select_left_video(self):
        fname = self._select_video_safe()
        if fname is not None:
            try:
                self.reader.create_left_reader(fname)
            except Exception as e:
                messagebox.showerror(type(e).__name__, str(e))
            self._on_select_canvas_update(self.reader.left_pos, self.reader.right_pos)
        self._update_canvas_image()
        self.update_title()

    def select_right_video(self):
        fname = self._select_video_safe()
        if fname is not None:
            try:
                self.reader.create_right_reader(fname)
            except Exception as e:
                messagebox.showerror(type(e).__name__, str(e))
            self._on_select_canvas_update(self.reader.right_pos, self.reader.left_pos)
        self._update_canvas_image()
        self.update_title()

    def create_menu(self):
        menu_bar = tk.Menu(self)
        self.master.config(menu=menu_bar)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label=_("Open left"), command=self.select_left_video)
        file_menu.add_command(label=_("Open right"), command=self.select_right_video)
        file_menu.add_separator()
        file_menu.add_command(label=_("Save as GIF..."), command=None)
        file_menu.add_command(label=_("Save as video..."), command=None)
        file_menu.add_separator()
        file_menu.add_command(label=_("Exit"), command=self.handle_close)
        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        view_menu = tk.Menu(menu_bar, tearoff=0)
        view_menu.add_radiobutton(
            label=_("Side-by-side"), command=self.select_composer_type("sbs")
        )
        view_menu.add_radiobutton(
            label=_("Chess pattern"), command=self.select_composer_type("chess")
        )
        view_menu.add_radiobutton(
            label=_("Curtain"), command=self.select_composer_type("split")
        )
        view_menu.invoke(0)
        menu_bar.add_cascade(label=_("View"), menu=view_menu)

        metrics_menu = tk.Menu(menu_bar, tearoff=0)
        for metric_label, (bool_var, query) in self.metrics:
            metrics_menu.add_checkbutton(
                label=metric_label,
                onvalue=1,
                offvalue=0,
                variable=bool_var,
                command=self.update_metrics,
            )
        menu_bar.add_cascade(label=_("Metrics"), menu=metrics_menu)

    def select_composer_type(self, composer_type: str):
        def wrapper():
            self.reader.composer_type = composer_type
            self.reader.last_input["read_frame"] = None  # drop cache
            self._update_canvas_image()

        return wrapper

    def update_title(self):
        left_file = self.reader.left_file
        right_file = self.reader.right_file
        if left_file:
            left_file = os.path.basename(left_file)
        if right_file:
            right_file = os.path.basename(right_file)
        self.master.title(f"{left_file} vs {right_file} | CoVid")

    def update_metrics(self):
        self.reader.metrics = [
            (label, query) for label, (v, query) in self.metrics if v.get()
        ]
        self.reader.last_input["read_frame"] = None  # drop cache
        self._update_canvas_image()


def main():
    app = App(title="<None> and <None> | CoVid")
    app.master.geometry("600x400")

    # app.reader.create_left_reader(
    #     os.path.join(
    #         os.path.dirname(__file__), "..", "samples", "foreman_crf30_short.mp4"
    #     )
    # )
    # app.reader.create_right_reader(
    #     os.path.join(
    #         os.path.dirname(__file__), "..", "samples", "foreman_crf40_short.mp4"
    #     )
    # )
    app.update_title()

    app.mainloop()


if __name__ == "__main__":
    main()
