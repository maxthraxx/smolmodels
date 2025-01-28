"""
Module: ProcessExecutor for Isolated Python Code Execution

This module provides an implementation of the `Executor` interface for executing Python code snippets
in an isolated process. It captures stdout, stderr, exceptions, and stack traces, and enforces
timeout limits on execution.

Classes:
    - RedirectQueue: A helper class to redirect stdout and stderr to a multiprocessing Queue.
    - ProcessExecutor: A class to execute Python code snippets in an isolated process.

Usage:
    Create an instance of `ProcessExecutor`, providing the Python code, working directory, and timeout.
    Call the `run` method to execute the code and return the results in an `ExecutionResult` object.

Exceptions:
    - Raises `RuntimeError` if the child process fails unexpectedly.

"""

import logging
import subprocess
import sys
import time
import pandas as pd
from pathlib import Path

from smolmodels.internal.common.utils.response import extract_performance
from smolmodels.internal.models.execution.executor import ExecutionResult, Executor
from smolmodels.config import config

logger = logging.getLogger(__name__)


class ProcessExecutor(Executor):
    """
    Execute Python code snippets in an isolated process.

    The `ProcessExecutor` class implements the `Executor` interface, allowing Python code
    snippets to be executed with strict isolation, output capture, and timeout enforcement.
    """

    def __init__(
        self,
        execution_id: str,
        code: str,
        working_dir: Path | str,
        dataset: pd.DataFrame,
        code_execution_file_name: str = config.execution.runfile_name,
        timeout: int = config.execution.timeout,
    ):
        """
        Initialize the ProcessExecutor.

        Args:
            code (str): The Python code to execute.
            working_dir (Path | str): The working directory for execution.
            timeout (int): The maximum allowed execution time in seconds.
            code_execution_file_name (str): The filename to use for the executed script.
        """
        super().__init__(code, timeout)
        # Create a unique working directory for this execution
        self.working_dir = Path(working_dir).resolve() / execution_id
        self.working_dir.mkdir(parents=True, exist_ok=True)
        # Set the file names for the code and training data
        self.code_file_name = code_execution_file_name
        self.dataset = dataset

    def run(self) -> ExecutionResult:
        """Execute code in a subprocess and return results."""
        logger.debug(f"ProcessExecutor is executing code with working directory: {self.working_dir}")
        start_time = time.time()

        # Write code to file
        code_file: Path = self.working_dir / self.code_file_name
        with open(code_file, "w") as f:
            f.write(self.code)

        # Write dataset to file
        dataset_file: Path = self.working_dir / config.execution.training_data_path
        self.dataset.to_csv(dataset_file, index=False)

        try:
            # Execute the code in a subprocess
            process = subprocess.Popen(
                [sys.executable, str(code_file)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.working_dir),
                text=True,
            )

            stdout, stderr = process.communicate(timeout=self.timeout)
            exec_time = time.time() - start_time

            # Collect all model artefacts created by the execution
            model_artifacts = []
            for file in self.working_dir.iterdir():
                if file != code_file:
                    model_artifacts.append(str(file))

            if process.returncode != 0:
                return ExecutionResult(
                    term_out=[stdout],
                    exec_time=exec_time,
                    exception=RuntimeError(stderr),
                    model_artifacts=model_artifacts,
                )

            # Parse performance from last line of stdout

            return ExecutionResult(
                term_out=[stdout],
                exec_time=exec_time,
                model_artifacts=model_artifacts,
                performance=extract_performance(stdout),
            )

        except subprocess.TimeoutExpired:
            process.kill()
            return ExecutionResult(
                term_out=[],
                exec_time=self.timeout,
                exception=TimeoutError(f"Execution exceeded {self.timeout}s timeout"),
            )

    def cleanup(self):
        """Required by abstract base class."""
        pass
