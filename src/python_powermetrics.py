from datetime import datetime
import subprocess
import time
import re
import numpy as np
import multiprocessing as mp
import queue


class CapturePowermetrics:
    def __init__(self):
        self.parent_conn, self.child_conn = mp.Pipe()
        self.data_queue = mp.Queue()
        self.termination_event = mp.Event()
        self.process = None

    def __enter__(self):
        self.process = mp.Process(
            target=self._worker,
            args=(self.child_conn, self.data_queue, self.termination_event),
        )
        self.process.start()
        return self

    def _keep_line(self, line):
        if line.startswith("*** Sampled system activity ("):
            return True
        elif line.startswith("CPU Power"):
            return True
        elif line.startswith("GPU Power"):
            return True
        elif line.startswith("ANE Power"):
            return True
        else:
            return False

    def _worker(self, conn, data_queue, termination_event):
        with subprocess.Popen(
            ["powermetrics", "--samplers", "cpu_power", "--sample-rate", "100"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            try:
                while not termination_event.is_set():
                    line = proc.stdout.readline()
                    if line:
                        if self._keep_line(line):
                            data_queue.put(line)
                    else:
                        time.sleep(0.1)

            except Exception as e:
                data_queue.put(f"Error: {e}")
            finally:
                proc.terminate()

        conn.send("Done")
        conn.close()

    def __exit__(self, exc_type, exc_value, traceback):
        self.termination_event.set()
        self.parent_conn.recv()
        self.process.join()

        collected_data = []
        while not self.data_queue.empty():
            try:
                collected_data.append(self.data_queue.get_nowait())
            except queue.Empty:
                break

        self.process_data(collected_data)

    def process_data(self, data):
        sample_times = []
        cpu_power = []
        gpu_power = []
        ane_power = []
        for line in data:
            if line.startswith("*** Sampled system activity ("):
                match = re.search(r"\((.*?)\)", line)
                date_string = match.group(1)
                dt = datetime.strptime(date_string, "%a %b %d %H:%M:%S %Y %z")
                sample_times.append(float(dt.timestamp()))
            elif line.startswith("CPU Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                cpu_power.append(float(power))
            elif line.startswith("GPU Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                gpu_power.append(float(power))
            elif line.startswith("ANE Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                ane_power.append(float(power))

        CONVERSION_FACTOR_mWs_TO_J = 1e-3

        times = np.array(sample_times)
        cpu = np.array(cpu_power)
        gpu = np.array(gpu_power)
        ane = np.array(ane_power)

        cpu_mWs = np.trapz(cpu, times)
        gpu_mWs = np.trapz(gpu, times)
        ane_mWs = np.trapz(ane, times)

        cpu_J = cpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        gpu_J = gpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        ane_J = ane_mWs * CONVERSION_FACTOR_mWs_TO_J

        print("cpu energy:", cpu_J, "J")
        print("gpu energy:", gpu_J, "J")
        print("ane energy:", ane_J, "J")


if __name__ == "__main__":
    with CapturePowermetrics() as capture:
        time.sleep(2)
