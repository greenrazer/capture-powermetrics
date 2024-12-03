from datetime import datetime
import subprocess
import time
import re
import numpy as np
import multiprocessing as mp
import queue
import os


class CapturePowermetrics:
    def __init__(self, sample_rate: int = 100):
        self.sample_rate = sample_rate

        self.parent_conn, self.child_conn = mp.Pipe()
        self.data_queue = mp.Queue()
        self.termination_event = mp.Event()
        self.ane_seen_event = mp.Event()
        self.process = None
        self.finished = False

        self.sample_times_s = []
        self.cpu_power_mW = []
        self.gpu_power_mW = []
        self.ane_power_mW = []
        self.cpu_energy_J = 0.0
        self.gpu_energy_J = 0.0
        self.ane_energy_J = 0.0

    def __enter__(self):
        assert os.geteuid() == 0, "Must be root."
        self.process = mp.Process(
            target=self._worker,
            args=(
                self.child_conn,
                self.data_queue,
                self.termination_event,
                self.ane_seen_event,
            ),
        )
        self.process.start()
        self.ane_seen_event.wait()
        return self

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

        self.finished = True
        for line in collected_data:
            if line.startswith("*** Sampled system activity ("):
                match = re.search(r"\((.*?)\)", line)
                date_string = match.group(1)
                dt = datetime.strptime(date_string, "%a %b %d %H:%M:%S %Y %z")
                self.sample_times_s.append(float(dt.timestamp()))
            elif line.startswith("CPU Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                self.cpu_power_mW.append(float(power))
            elif line.startswith("GPU Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                self.gpu_power_mW.append(float(power))
            elif line.startswith("ANE Power"):
                power = line.split(":", maxsplit=1)[1].strip().split()[0]
                self.ane_power_mW.append(float(power))

        self._compute_energy()

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

    def _worker(self, conn, data_queue, termination_event, ane_seen_event):
        ane_power_detected = False
        with subprocess.Popen(
            [
                "powermetrics",
                "--samplers",
                "cpu_power",
                "--sample-rate",
                str(self.sample_rate),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as proc:
            try:
                while not termination_event.is_set():
                    line = proc.stdout.readline()
                    if line:
                        if self._keep_line(line):
                            if ane_power_detected:
                                data_queue.put(line)
                            elif line.startswith("ANE Power"):
                                ane_power_detected = True
                                ane_seen_event.set()
                    else:
                        time.sleep(0.1)

            except Exception as e:
                data_queue.put(f"Error: {e}")
            finally:
                proc.terminate()

        conn.send("Done")
        conn.close()

    def _compute_energy(self):
        CONVERSION_FACTOR_mWs_TO_J = 1e-3

        times = np.array(self.sample_times_s)
        cpu = np.array(self.cpu_power_mW)
        gpu = np.array(self.gpu_power_mW)
        ane = np.array(self.ane_power_mW)

        cpu_mWs = np.trapz(cpu, times)
        gpu_mWs = np.trapz(gpu, times)
        ane_mWs = np.trapz(ane, times)

        self.cpu_energy_J = cpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        self.gpu_energy_J = gpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        self.ane_energy_J = ane_mWs * CONVERSION_FACTOR_mWs_TO_J

    def __str__(self):
        if self.process == None:
            return "hasn't started"
        elif not self.finished:
            return "hasn't finished"
        else:
            return f"""
                cpu energy(J): {self.cpu_energy_J}
                gpu energy(J): {self.gpu_energy_J}
                ane energy(J): {self.ane_energy_J}
            """


if __name__ == "__main__":
    with CapturePowermetrics(sample_rate=100) as capture:
        time.sleep(2)
    print(capture)
    print(capture.cpu_energy_J)
