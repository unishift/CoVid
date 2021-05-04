import os
import gettext
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from PIL import ImageTk, Image
import numpy as np

import compose
import video_reader

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

        self.left_video: video_reader.FfmsReader = None
        self.right_video: video_reader.FfmsReader = None
        self.paused = False
        self.last_image = None
        self.need_reset_last_image = False
        self.composer = compose.Composer(
            compose.ComposeVerticalSplit,
            info_provide_func=lambda *args: "PSNR:24.07070707\nSSIM:228.14888",
            font_config=compose.FontConfig(),
        )

    def create_widgets(self):
        super().create_widgets()
        self.create_menu()

        self.C = tk.Canvas(self, background="gray75")
        self.C.grid(sticky="NEWS")
        self.controls = tk.Frame(self)
        self.controls.grid(sticky="EWS", row=1)

        self.back_fast = tk.Button(self.controls, text="<<", command=None)
        self.back_fast.grid(row=0, column=0, sticky="W")
        self.back = tk.Button(self.controls, text="<", command=None)
        self.back.grid(row=0, column=1, sticky="W")

        self.timeline = tk.Scale(self.controls, from_=0, to_=100, orient=tk.HORIZONTAL)
        self.timeline.grid(row=0, column=2, sticky="EW")

        self.forward = tk.Button(self.controls, text=">", command=None)
        self.forward.grid(row=0, column=3, sticky="E")
        self.forward_fast = tk.Button(self.controls, text=">>", command=None)
        self.forward_fast.grid(row=0, column=4, sticky="E")

        self.offset = tk.StringVar()
        self.offset.set("0")
        self.offset_box = tk.Spinbox(
            self.controls, from_=-100, to=100, textvariable=self.offset
        )
        self.offset_box.grid(row=1, column=2)

        self.master.bind("<Configure>", self.handle_resize)

    def configure_widgets(self):
        super().configure_widgets()
        self.rowconfigure(1, weight=0)  # fixed controls height
        self.controls.columnconfigure(2, weight=1)

    def _select_video_safe(self):
        file_name = filedialog.askopenfilename()
        if file_name is None:
            return
        try:
            return video_reader.FfmsReader(file_name)
        except video_reader.VideoOpenException as e:
            messagebox.showerror("Error!", f"Can't open {file_name} as video")
        return None

    def _sync_progress_bar_length(self):
        left_length = self.left_video.GetLength()
        right_length = self.right_video.GetLength()

        offset = int(self.offset.get())

        self.timeline.config(
            from_=max(-offset, 0), to=min(left_length - 1, right_length - 1 - offset)
        )

    def _sync_video_with_offset(self):
        assert self.left_video is not None and self.right_video is not None
        current_delta = (
            self.right_video.GetPlaybackFramePosition()
            - self.left_video.GetPlaybackFramePosition()
        )
        desired_delta = int(self.offset.get())
        if (
            current_delta != desired_delta
        ):  # If we need to fix offset, at first we try to move right video
            self.right_video.ShiftPlaybackFramePosition(desired_delta - current_delta)
        current_delta = (
            self.right_video.GetPlaybackFramePosition()
            - self.left_video.GetPlaybackFramePosition()
        )
        if current_delta != desired_delta:  # If it's not enough, we move left video
            self.left_video.ShiftPlaybackFramePosition(-(desired_delta - current_delta))
        current_delta = (
            self.right_video.GetPlaybackFramePosition()
            - self.left_video.GetPlaybackFramePosition()
        )
        if (
            current_delta != desired_delta
        ):  # Finally we understand that we can't fix offset and change the value back
            self.offset.set(str(current_delta))
        # Now we need to fix maximum progress_bar value as the offset might have an impact on it
        self._sync_progress_bar_length()

    def _videos_next_frame(self):
        canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
        if self.left_video is None and self.right_video is None:
            return
        if self.left_video is not None:
            left_frame, left_delta = self.left_video.GetNextFrame()
        if self.right_video is not None:
            right_frame, right_delta = self.right_video.GetNextFrame()

        if self.left_video is None:
            left_frame = np.zeros_like(right_frame)
            left_delta = 1000 / 24
        elif self.right_video is None:
            right_frame = np.zeros_like(left_frame)
            right_delta = 1000 / 24
        elif self.left_video.IsEnd() or self.right_video.IsEnd():
            return

        composed = self.composer.Compose(
            left_frame, right_frame, canvas_size_wh=canvas_size_wh
        )
        # resize_coeff = min(canvas_size_wh[0] / composed.width, canvas_size_wh[1] / composed.height)
        # composed = composed.resize(size=(int(composed.width * resize_coeff), int(composed.height * resize_coeff)),
        #                           resample=Image.BILINEAR)
        if self.last_image is None or self.need_reset_last_image:
            self.need_reset_last_image = False
            self.last_image = ImageTk.PhotoImage(composed)
            self.C.create_image(0, 0, anchor="nw", image=self.last_image)
        else:
            self.last_image.paste(composed)
        self.C.update()
        return left_delta

    def handle_resize(self, event):
        canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
        if self.left_video is not None:
            self.left_video.UpdateVideoSize(canvas_size_wh)
            self.left_video.ShiftPlaybackFramePosition(-1)
        if self.right_video is not None:
            self.right_video.UpdateVideoSize(canvas_size_wh)
            self.riht_video.ShiftPlaybackFramePosition(-1)
        self._videos_next_frame()
        self.need_reset_last_image = True

    def video_playback_update(self):
        if self.paused:
            return
        if self.left_video is not None and self.right_video is not None:
            cur_time = time.time()
            left_delta = self._videos_next_frame()
            elapsed_time = (time.time() - cur_time) * 1000
            print(elapsed_time)
            self.master.after(
                int(max(left_delta - elapsed_time, 1)), self.video_playback_update
            )

    def _check_start_timer(self, delay):
        if self.left_video is not None and self.right_video is not None:
            self.master.after(int(delay), self.video_playback_update)

    def _on_select_canvas_update(self, first_video, second_video):
        if second_video is not None:
            second_video.SetPlaybackFramePosition(0)
            self._sync_video_with_offset()
            self._sync_progress_bar_length()
        if first_video is not None:
            canvas_size_wh = self.C.winfo_width(), self.C.winfo_height()
            first_video.UpdateVideoSize(canvas_size_wh)
            left_delta = self._videos_next_frame()
            self._check_start_timer(left_delta)

    def select_left_video(self):
        self.left_video = self._select_video_safe()
        self._on_select_canvas_update(self.left_video, self.right_video)

    def select_right_video(self):
        self.right_video = self._select_video_safe()
        self._on_select_canvas_update(self.right_video, self.left_video)

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
        file_menu.add_command(label=_("Exit"), command=self.quit)
        menu_bar.add_cascade(label=_("File"), menu=file_menu)

        view_menu = tk.Menu(menu_bar, tearoff=0)
        view_menu.add_radiobutton(label=_("Side-by-side"), command=None)
        view_menu.add_radiobutton(label=_("Chess pattern"), command=None)
        view_menu.add_radiobutton(label=_("Curtain"), command=None)
        view_menu.invoke(0)
        menu_bar.add_cascade(label=_("View"), menu=view_menu)

        metrics_menu = tk.Menu(menu_bar, tearoff=0)
        metrics_menu.add_checkbutton(label="PSNR", command=None)
        metrics_menu.add_checkbutton(label="SSIM", command=None)
        metrics_menu.add_checkbutton(label="NIQE", command=None)
        menu_bar.add_cascade(label=_("Metrics"), menu=metrics_menu)


def main():
    app = App(title="<None> and <None> | CoVid")
    app.master.geometry("600x400")
    app.mainloop()


if __name__ == "__main__":
    main()
