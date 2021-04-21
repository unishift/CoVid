import tkinter as tk


class Application(tk.Frame):
    '''Sample tkinter application class'''

    def __init__(self, master=None, title="<application>", **kwargs):
        '''Create root window with frame, tune weight and resize'''
        super().__init__(master, **kwargs)
        self.master.title(title)
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.grid(sticky="NEWS")
        self.create_widgets()
        self.configure_widgets()

    def create_widgets(self):
        '''Create all the widgets'''

    @staticmethod
    def make_flexible(grid):
        for column in range(grid.grid_size()[0]):
            grid.columnconfigure(column, weight=1)
        for row in range(grid.grid_size()[1]):
            grid.rowconfigure(row, weight=1)

    def configure_widgets(self):
        self.make_flexible(self)


class App(Application):
    def create_widgets(self):
        super().create_widgets()
        self.create_menu()

        self.C = tk.Canvas(self, background='gray75')
        self.C.grid(sticky='NEWS')
        self.controls = tk.Frame(self)
        self.controls.grid(sticky='EWS', row=1)

        self.back_fast = tk.Button(self.controls, text='<<', command=None)
        self.back_fast.grid(row=0, column=0, sticky='W')
        self.back = tk.Button(self.controls, text='<', command=None)
        self.back.grid(row=0, column=1, sticky='W')
        
        self.timeline = tk.Scale(self.controls, from_=0, to_=100, orient=tk.HORIZONTAL)
        self.timeline.grid(row=0, column=2, sticky='EW')
        
        self.forward = tk.Button(self.controls, text='>', command=None)
        self.forward.grid(row=0, column=3, sticky='E')
        self.forward_fast = tk.Button(self.controls, text='>>', command=None)
        self.forward_fast.grid(row=0, column=4, sticky='E')

        self.offset = tk.StringVar()
        self.offset.set('0')
        self.offset_box = tk.Spinbox(self.controls, from_=-100, to=100, textvariable=self.offset)
        self.offset_box.grid(row=1, column=2)

    def configure_widgets(self):
        super().configure_widgets()
        self.rowconfigure(1, weight=0)  # fixed controls height
        self.controls.columnconfigure(2, weight=1)

    def create_menu(self):
        menu_bar = tk.Menu(self)
        self.master.config(menu=menu_bar)

        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label='Open left', command=None)
        file_menu.add_command(label='Open right', command=None)
        file_menu.add_separator()
        file_menu.add_command(label='Save as GIF...', command=None)
        file_menu.add_command(label='Save as video...', command=None)
        file_menu.add_separator()
        file_menu.add_command(label='Exit', command=self.quit)
        menu_bar.add_cascade(label='File', menu=file_menu)
        
        view_menu = tk.Menu(menu_bar, tearoff=0)
        view_menu.add_radiobutton(label='Side-by-side', command=None)
        view_menu.add_radiobutton(label='Chess pattern', command=None)
        view_menu.add_radiobutton(label='Curtain', command=None)
        view_menu.invoke(0)
        menu_bar.add_cascade(label='View', menu=view_menu)

        metrics_menu = tk.Menu(menu_bar, tearoff=0)
        metrics_menu.add_checkbutton(label='PSNR', command=None)
        metrics_menu.add_checkbutton(label='SSIM', command=None)
        metrics_menu.add_checkbutton(label='NIQE', command=None)
        menu_bar.add_cascade(label='Metrics', menu=metrics_menu)


def main():
    app = App(title="<None> and <None> | CoVid")
    app.master.geometry('600x400')
    app.mainloop()


if __name__ == '__main__':
    main()
