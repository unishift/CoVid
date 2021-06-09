import sys
import json
from pathlib import Path
from typing import List, Union


class VQMTMetrics:
    PSNR_Y = dict(metric_name="psnr", color_component="Y")
    SSIM_Y = dict(metric_name="ssim", color_component="Y")
    NIQE_Y = dict(
        metric_name="niqe", color_component="Y", compaired_files=[1]
    )  # typo from VQMT
    VMAF061_Y = dict(metric_name="vmaf", color_component="Y", value_id="VMAF061")

    def __init__(self):
        self.metrics: dict = None

    def load(self, metrics_path: Union[str, Path]):
        try:
            with open(metrics_path, "r") as f:
                self.metrics = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.metrics = None
            print(f"Can't load metrics from {metrics_path}: {e}", file=sys.stderr)

    @staticmethod
    def _get_metric_col(head_metrics: List[dict], query: dict):
        """
        Find metric in VQMT head metrics list
        Args:
            head_metrics: metrics from head section
            query: requested metric fields
        Returns: metric col if exists otherwise raises IndexError
        """
        for metric in head_metrics:
            for k, v in query.items():
                if metric[k] != v:
                    break
            else:
                return metric["col"]
        raise IndexError(query)

    def query(self, frame_idx: int, requested_metrics: List[dict]):
        """
        Return requested metrics for specific frame if exists
        Args:
            frame_idx: index of frame to read
            requested_metrics: list of requested metrics
        Returns: list of metrics
        """
        if self.metrics is None:
            return [None] * len(requested_metrics)
        result = []
        frame_metrics = self.metrics["values"][frame_idx]["data"]
        for query in requested_metrics:
            try:
                col = self._get_metric_col(self.metrics["head"]["metrics"], query)
                result.append(frame_metrics[col])
            except IndexError:
                result.append(None)
        return result
