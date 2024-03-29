from qtpy.QtCore import QObject
from qtpy.QtCore import QRunnable
from PyQt5.QtCore import pyqtSignal, pyqtSlot
import traceback
import sys
from multiprocessing import Process, shared_memory, Pool
import numpy as np


class _utils_compute:

    def create_shared_images(self, dataset_list = None, channel_list = None):

        if self.verbose:
            print("Creating shared images")

        if dataset_list is None:
            dataset_list = list(self.dataset_dict.keys())
        else:
            dataset_list = [dataset for dataset in dataset_list if dataset in self.dataset_dict.keys()]

        self.shared_images = []

        for dataset_name in dataset_list:

            if channel_list is None:
                channel_names = list(self.dataset_dict[dataset_name].keys())
            else:
                channel_names = [channel for channel in channel_list if channel in self.dataset_dict[dataset_name].keys()]

            for channel_name in channel_names:

                if channel_name in self.dataset_dict[dataset_name].keys():

                    channel_dict = self.dataset_dict[dataset_name][channel_name]

                    image = channel_dict.pop("data")

                    shared_mem = shared_memory.SharedMemory(create=True, size=image.nbytes)
                    shared_memory_name = shared_mem.name
                    shared_image = np.ndarray(image.shape, dtype=image.dtype, buffer=shared_mem.buf)
                    shared_image[:] = image[:]

                    n_frames = image.shape[0]

                    self.shared_images.append({"dataset": dataset_name,
                                               "channel": channel_name,
                                               "gap_label": channel_dict["gap_label"],
                                               "sequence_label": channel_dict["sequence_label"],
                                               "n_frames": n_frames,
                                               "shape": image.shape,
                                               "dtype": image.dtype,
                                               "shared_mem": shared_mem,
                                               "shared_memory_name": shared_memory_name})

        return self.shared_images

    def restore_shared_images(self):

        if self.verbose:
            print("Restoring shared images")

        if hasattr(self, "shared_images"):

            for dat in self.shared_images:
                try:
                    shared_mem = dat["shared_mem"]

                    np_array = np.ndarray(dat["shape"], dtype=dat["dtype"], buffer=shared_mem.buf)

                    self.dataset_dict[dat["dataset"]][dat["channel"]]["data"] = np_array.copy()

                    shared_mem.close()
                    shared_mem.unlink()

                except:
                    print(traceback.format_exc())
                    pass

    def create_shared_frames(self):

        if self.verbose:
            print("Creating shared frames")

        self.shared_frames = []

        for dataset_name, dataset_dict in self.dataset_dict.items():
            for channel_name, channel_dict in dataset_dict.items():

                image = channel_dict.pop("data")

                image_dict = {"dataset": dataset_name,
                              "channel": channel_name,
                              "gap_label": channel_dict["gap_label"],
                              "sequence_label": channel_dict["sequence_label"],
                              "n_frames": image.shape[0],
                              "shape": image.shape,
                              "dtype": image.dtype,
                              "frame_dict":{},
                              }

                for frame_index, frame in enumerate(image):

                    if frame_index not in image_dict["frame_dict"]:
                        image_dict["frame_dict"][frame_index] = {}

                    shared_mem = shared_memory.SharedMemory(create=True, size=frame.nbytes)
                    shared_frame = np.ndarray(frame.shape, dtype=frame.dtype, buffer=shared_mem.buf)
                    shared_frame[:] = frame[:]

                    image_dict["frame_dict"][frame_index] = {"frame_index": frame_index,
                                                             "dataset": dataset_name,
                                                                "channel": channel_name,
                                                                "shared_mem": shared_mem,
                                                                "shape": frame.shape,
                                                                "dtype": frame.dtype,
                                                                }

                self.shared_frames.append(image_dict)

        return self.shared_frames

    def restore_shared_frames(self):

        if self.verbose:
            print("Restoring shared frames")

        if hasattr(self, "shared_frames"):

            for image_dict in self.shared_frames:

                try:

                    frame_dict = image_dict["frame_dict"]

                    image = []

                    for frame_index, frame_dict in frame_dict.items():

                        shared_mem = frame_dict["shared_mem"]

                        frame = np.ndarray(frame_dict["shape"], dtype=frame_dict["dtype"], buffer=shared_mem.buf)

                        image.append(frame.copy())

                        shared_mem.close()
                        shared_mem.unlink()

                    image = np.stack(image, axis=0)

                    self.dataset_dict[image_dict["dataset"]][image_dict["channel"]]["data"] = image

                    shared_mem.close()
                    shared_mem.unlink()

                except:
                    print(traceback.format_exc())
                    pass


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc() )

    result
        object data returned from processing, anything

    progress
        int indicating % progress

    """

    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)

class Worker(QRunnable):
    """
    Worker thread

    Inherits from QRunnable to handler worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function

    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        # Add the callback to our kwargs
        self.kwargs["progress_callback"] = self.signals.progress

        self._is_stopped = False  # Stop flag

    @pyqtSlot()
    def run(self):
        """
        Initialise the runner function with passed args, kwargs.
        """

        # Retrieve args/kwargs here; and fire processing using them
        try:

            while not self._is_stopped:
                result = self.fn(*self.args, **self.kwargs)
                self.signals.result.emit(result)  # Emit the result
                self._is_stopped = True
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        finally:
            self.signals.finished.emit()  # Done

    def result(self):
        return self.fn(*self.args, **self.kwargs)

    def stop(self):

        self._is_stopped = True
        self.signals.finished.emit()