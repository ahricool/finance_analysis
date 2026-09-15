# -*- coding: utf-8 -*-
"""
===================================
Autocomplete PR0 Unit Tests
===================================

Test backend data contract extensions:
- TaskInfo dataclass extension
- Task queue accepts new fields
- Backward compatibility
"""

from finance_analysis.tasks.queue import (
    TaskInfo,
    AnalysisTaskQueue,
    reset_task_state_for_tests,
)
from tests.task_repo_fakes import FakeTaskRecordRepository


class TestTaskInfo:
    """Test TaskInfo dataclass"""

    def test_task_info_with_new_fields(self):
        """Test that TaskInfo contains new fields"""
        task = TaskInfo(
            task_id="test123",
            stock_code="600519",
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="autocomplete",
        )
        d = task.to_dict()
        assert "original_query" in d
        assert "selection_source" in d
        assert d["original_query"] == "茅台"
        assert d["selection_source"] == "autocomplete"

    def test_task_info_backward_compatible(self):
        """Test TaskInfo backward compatibility: works fine without new fields"""
        task = TaskInfo(
            task_id="test123",
            stock_code="600519",
        )
        d = task.to_dict()
        assert d["original_query"] is None
        assert d["selection_source"] is None

    def test_task_info_copy_includes_new_fields(self):
        """Test that TaskInfo.copy() includes new fields"""
        task = TaskInfo(
            task_id="test123",
            stock_code="600519",
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="autocomplete",
        )
        copied = task.copy()
        assert copied.original_query == "茅台"
        assert copied.selection_source == "autocomplete"


class TestTaskQueue:
    """Test task queue"""

    def setup_method(self):
        self._original_instance = AnalysisTaskQueue._instance
        reset_task_state_for_tests()

    def teardown_method(self):
        reset_task_state_for_tests()
        AnalysisTaskQueue._instance = self._original_instance

    @staticmethod
    def _build_queue():
        return AnalysisTaskQueue(max_workers=1, repository=FakeTaskRecordRepository())

    def test_task_queue_accepts_new_fields(self):
        """Test task queue accepts new fields"""
        queue = self._build_queue()
        tasks, _duplicates = queue.submit_tasks_batch(
            stock_codes=["600519"],
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="autocomplete",
        )
        assert len(tasks) == 1
        assert tasks[0].stock_name == "贵州茅台"
        assert tasks[0].original_query == "茅台"
        assert tasks[0].selection_source == "autocomplete"

    def test_task_queue_backward_compatible(self):
        """Test task queue backward compatibility: works fine without new fields"""
        queue = self._build_queue()
        tasks, _duplicates = queue.submit_tasks_batch(
            stock_codes=["600519"],
        )
        assert len(tasks) == 1
        assert tasks[0].original_query is None
        assert tasks[0].selection_source is None

    def test_task_queue_batch_with_new_fields(self):
        """Test support for new fields during batch submission"""
        queue = self._build_queue()
        tasks, _duplicates = queue.submit_tasks_batch(
            stock_codes=["600519", "000001"],
            stock_name="批量股票",
            original_query="600519,000001",
            selection_source="import",
        )
        assert len(tasks) == 2
        for task in tasks:
            assert task.stock_name == "批量股票"
            assert task.original_query == "600519,000001"
            assert task.selection_source == "import"

    def test_task_queue_allows_repeated_submissions_with_new_fields(self):
        queue = self._build_queue()
        stock_code = "600519"

        # First submission
        tasks1, dups1 = queue.submit_tasks_batch(
            stock_codes=[stock_code],
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="autocomplete",
        )
        assert len(tasks1) == 1
        assert len(dups1) == 0

        # Task history is not used as an execution mutex.
        tasks2, dups2 = queue.submit_tasks_batch(
            stock_codes=[stock_code],
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="manual",
        )
        assert len(tasks2) == 1
        assert len(dups2) == 0
        assert tasks2[0].task_id != tasks1[0].task_id


class TestIntegration:
    """Integration Tests"""

    def setup_method(self):
        self._original_instance = AnalysisTaskQueue._instance
        reset_task_state_for_tests()

    def teardown_method(self):
        reset_task_state_for_tests()
        AnalysisTaskQueue._instance = self._original_instance

    def test_end_to_end_flow_with_autocomplete(self):
        """Test end-to-end flow: autocomplete metadata -> task creation"""
        queue = AnalysisTaskQueue(max_workers=1, repository=FakeTaskRecordRepository())
        tasks, _duplicates = queue.submit_tasks_batch(
            stock_codes=["600519.SH"],
            stock_name="贵州茅台",
            original_query="茅台",
            selection_source="autocomplete",
            report_type="detailed",
        )

        assert len(tasks) == 1
        task = tasks[0]
        assert task.stock_code == "600519.SH"
        assert task.stock_name == "贵州茅台"
        assert task.original_query == "茅台"
        assert task.selection_source == "autocomplete"
        assert task.report_type == "detailed"

    def test_end_to_end_flow_manual_input(self):
        """Test end-to-end flow: manual input metadata -> task creation"""
        queue = AnalysisTaskQueue(max_workers=1, repository=FakeTaskRecordRepository())
        tasks, _duplicates = queue.submit_tasks_batch(
            stock_codes=["600519"],
            selection_source="manual",
            report_type="detailed",
        )

        assert len(tasks) == 1
        task = tasks[0]
        assert task.stock_code == "600519"
        assert task.selection_source == "manual"
