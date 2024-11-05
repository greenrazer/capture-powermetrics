from datetime import datetime
import subprocess
import threading
import os
import signal
import time
import re
import numpy as np

class CapturePowermetrics:
    def __init__(self):
        self.command = ["powermetrics", "--samplers", "cpu_power"]

        self.process = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.pid = os.getpid()
        self.ok = False

        self.sample_times = []
        self.cpu_power = []
        self.gpu_power = []
        self.ane_power = []

    def _capture_stdout(self):
        for line in iter(self.process.stdout.readline, b''):
            self.ok = True
            decoded_line = line.decode('utf-8')
            if decoded_line.startswith("*** Sampled system activity ("):
                match = re.search(r'\((.*?)\)', decoded_line)
                date_string = match.group(1)
                dt = datetime.strptime(date_string, "%a %b %d %H:%M:%S %Y %z")
                self.sample_times.append(float(dt.timestamp()))
            elif decoded_line.startswith("CPU Power"):
                power = decoded_line.split(":", maxsplit=1)[1].strip().split()[0]
                self.cpu_power.append(float(power))
            elif decoded_line.startswith("GPU Power"):
                power = decoded_line.split(":", maxsplit=1)[1].strip().split()[0]
                self.gpu_power.append(float(power))
            elif decoded_line.startswith("ANE Power"):
                power = decoded_line.split(":", maxsplit=1)[1].strip().split()[0]
                self.ane_power.append(float(power))

    def _capture_stderr(self):
        for line in iter(self.process.stderr.readline, b''):
            decoded_line = line.decode('utf-8')
            print()
            print(f"Exception: {decoded_line}")
            if not self.ok:
                os.kill(self.pid, signal.SIGKILL)

    def __enter__(self):
        self.process = subprocess.Popen(
            " ".join(self.command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True
        )

        self.stdout_thread = threading.Thread(target=self._capture_stdout)
        self.stderr_thread = threading.Thread(target=self._capture_stderr)

        self.stdout_thread.start()
        self.stderr_thread.start()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.process.terminate()
        self.process.wait()

        self.stdout_thread.join()
        self.stderr_thread.join()

        CONVERSION_FACTOR_mWs_TO_J = 1e-3

        times = np.array(self.sample_times)
        cpu = np.array(self.cpu_power)
        gpu = np.array(self.gpu_power)
        ane = np.array(self.ane_power)

        cpu_mWs = np.trapezoid(cpu, times)
        gpu_mWs = np.trapezoid(gpu, times)
        ane_mWs = np.trapezoid(ane, times)

        cpu_J = cpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        gpu_J = gpu_mWs * CONVERSION_FACTOR_mWs_TO_J
        ane_J = ane_mWs * CONVERSION_FACTOR_mWs_TO_J

        print("cpu energy:", cpu_J, "J")
        print("gpu energy:", gpu_J, "J")
        print("ane energy:", ane_J, "J")

if __name__ == "__main__":
    with CapturePowermetrics() as capture:
        time.sleep(20)