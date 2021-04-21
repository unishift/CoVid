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
        for column in range(self.grid_size()[0]):
            self.columnconfigure(column, weight=1)
        for row in range(self.grid_size()[1]):
            self.rowconfigure(row, weight=1)

    def create_widgets(self):
        '''Create all the widgets'''


class App(Application):
    def create_widgets(self):
        super().create_widgets()
        self.create_menu()

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
    	menu_bar.add_cascade(label='View', menu=metrics_menu)


def main():
	app = App(title="<None> and <None> | CoVid")
	app.master.geometry('200x200')
	app.mainloop()


if __name__ == '__main__':
	main()
