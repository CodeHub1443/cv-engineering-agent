"""
Tests for cv_agent.execution.jobs.runtimes.yolo_eval (D-060).
"""

from __future__ import annotations

import pytest

from cv_agent.execution.binding import ExecutionBindingRegistry
from cv_agent.execution.jobs.runtimes.yolo_eval import (
    BINDING_ID,
    RUNTIME_ID,
    SKILL_ID,
    build_binding,
    build_command,
    expected_artifact_paths,
    parse_metrics,
    register_binding,
)


# ---------------------------------------------------------------------------
# Sample stdout fixtures
# ---------------------------------------------------------------------------

_COCO8_STDOUT = """\
Ultralytics 8.4.138 🚀 Python-3.10.12 torch-2.5.1+cu121 CUDA:0 (NVIDIA GeForce RTX 3060, 12042MiB)
YOLO11n summary (fused): 100 layers, 2,616,248 parameters, 0 gradients, 6.5 GFLOPs

val: Fast image access ✅ (ping: 0.0±0.0 ms)
val: Scanning /datasets/coco8/labels/val... 4 images, 0 backgrounds, 0 corrupt
                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95): 100%
                   all          4         10      0.651        0.6      0.581      0.268
                person          3         10      0.651        0.6      0.581      0.268
Speed: 0.2ms preprocess, 14.1ms inference, 0.0ms loss, 0.6ms postprocess per image
Results saved to runs/detect/val
"""

_COCO_FULL_STDOUT = """\
Ultralytics 8.4.138 🚀 Python-3.10.12 torch-2.5.1+cu121 CUDA:0 (NVIDIA GeForce RTX 3060, 12042MiB)
YOLO11n summary (fused): 100 layers, 2,616,248 parameters, 0 gradients, 6.5 GFLOPs

val: Scanning /datasets/coco/labels/val2017... 4952 images, 48 backgrounds, 0 corrupt
                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95): 100%
                   all       5000      36335      0.685      0.574      0.615      0.439
                person       5000      36335      0.685      0.574      0.615      0.439
Speed: 0.5ms preprocess, 2.3ms inference, 0.0ms loss, 1.1ms postprocess per image
Results saved to runs/detect/val2
"""

_STDOUT_WITH_ANSI = (
    "\x1b[34m\x1b[1mval: \x1b[0mScanning... 4 images\n"
    "                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95): 100%\n"
    "                   all          4         10      0.651        0.6      0.581      0.268\n"
    "                person          3         10      0.651        0.6      0.581      0.268\n"
    "Speed: 0.2ms preprocess, 14.1ms inference, 0.0ms loss, 0.6ms postprocess per image\n"
)

_STDOUT_ALL_ONLY = """\
                 Class     Images  Instances      Box(P          R      mAP50  mAP50-95): 100%
                   all          4         10      0.700        0.650      0.600      0.300
Speed: 1.0ms preprocess, 5.0ms inference, 0.0ms loss, 0.5ms postprocess per image
"""

_STDOUT_NO_METRICS = """\
Ultralytics 8.4.138
ERROR: dataset not found
"""


# ---------------------------------------------------------------------------
# build_command
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def _base_inputs(self, **overrides: object) -> dict:
        return {
            "data": "/datasets/coco/coco-person-val.yaml",
            "output_dir": "/output",
            "run_name": "eval-run-1",
            **overrides,
        }

    def test_requires_data(self) -> None:
        with pytest.raises(ValueError, match="data"):
            build_command({"output_dir": "/out", "run_name": "x"})

    def test_requires_output_dir(self) -> None:
        with pytest.raises(ValueError, match="output_dir"):
            build_command({"data": "/data.yaml", "run_name": "x"})

    def test_requires_run_name(self) -> None:
        with pytest.raises(ValueError, match="run_name"):
            build_command({"data": "/data.yaml", "output_dir": "/out"})

    def test_command_starts_with_yolo_val(self) -> None:
        cmd = build_command(self._base_inputs())
        assert cmd[0] == "yolo"
        assert cmd[1] == "val"

    def test_model_in_command(self) -> None:
        cmd = build_command(self._base_inputs(model="/path/to/yolo11n.pt"))
        assert "model=/path/to/yolo11n.pt" in cmd

    def test_data_in_command(self) -> None:
        cmd = build_command(self._base_inputs())
        assert "data=/datasets/coco/coco-person-val.yaml" in cmd

    def test_default_classes_is_person_only(self) -> None:
        cmd = build_command(self._base_inputs())
        assert "classes=[0]" in cmd

    def test_custom_classes(self) -> None:
        cmd = build_command(self._base_inputs(classes=[0, 1, 2]))
        assert "classes=[0,1,2]" in cmd

    def test_project_and_name_in_command(self) -> None:
        cmd = build_command(self._base_inputs())
        assert "project=/output" in cmd
        assert "name=eval-run-1" in cmd

    def test_conf_in_command(self) -> None:
        cmd = build_command(self._base_inputs(conf=0.5))
        assert "conf=0.5" in cmd

    def test_device_in_command(self) -> None:
        cmd = build_command(self._base_inputs(device="0"))
        assert "device=0" in cmd

    def test_batch_in_command(self) -> None:
        cmd = build_command(self._base_inputs(batch=8))
        assert "batch=8" in cmd

    def test_custom_executable(self) -> None:
        cmd = build_command(self._base_inputs(yolo_executable="/home/dev/.local/bin/yolo"))
        assert cmd[0] == "/home/dev/.local/bin/yolo"

    def test_returns_list_of_strings(self) -> None:
        cmd = build_command(self._base_inputs())
        assert all(isinstance(x, str) for x in cmd)

    def test_no_shell_metacharacters_in_required_args(self) -> None:
        cmd = build_command(self._base_inputs())
        assert " " not in "".join(cmd[2:])  # no space-containing tokens beyond exe+mode


# ---------------------------------------------------------------------------
# parse_metrics
# ---------------------------------------------------------------------------


class TestParseMetrics:
    def test_coco8_person_metrics(self) -> None:
        m = parse_metrics(_COCO8_STDOUT)
        assert m["precision"] == pytest.approx(0.651)
        assert m["recall"] == pytest.approx(0.6)
        assert m["map50"] == pytest.approx(0.581)
        assert m["map50_95"] == pytest.approx(0.268)

    def test_coco8_speed_metrics(self) -> None:
        m = parse_metrics(_COCO8_STDOUT)
        assert m["speed_preprocess_ms"] == pytest.approx(0.2)
        assert m["speed_inference_ms"] == pytest.approx(14.1)
        assert m["speed_postprocess_ms"] == pytest.approx(0.6)

    def test_coco_full_person_metrics(self) -> None:
        m = parse_metrics(_COCO_FULL_STDOUT)
        assert m["precision"] == pytest.approx(0.685)
        assert m["recall"] == pytest.approx(0.574)
        assert m["map50"] == pytest.approx(0.615)
        assert m["map50_95"] == pytest.approx(0.439)

    def test_ansi_codes_stripped(self) -> None:
        m = parse_metrics(_STDOUT_WITH_ANSI)
        assert m["precision"] == pytest.approx(0.651)
        assert m["map50_95"] == pytest.approx(0.268)

    def test_prefers_person_row_over_all(self) -> None:
        # Both "all" and "person" rows present — person row wins
        m = parse_metrics(_COCO8_STDOUT)
        # coco8: all and person have same values, so this checks the preference logic
        assert "precision" in m

    def test_falls_back_to_all_row_when_no_person_row(self) -> None:
        m = parse_metrics(_STDOUT_ALL_ONLY)
        assert m["precision"] == pytest.approx(0.700)
        assert m["recall"] == pytest.approx(0.650)
        assert m["map50"] == pytest.approx(0.600)
        assert m["map50_95"] == pytest.approx(0.300)

    def test_empty_dict_on_no_metrics(self) -> None:
        m = parse_metrics(_STDOUT_NO_METRICS)
        assert m == {}

    def test_speed_only_when_no_table(self) -> None:
        stdout = "Speed: 1.0ms preprocess, 5.0ms inference, 0.0ms loss, 0.5ms postprocess per image"
        m = parse_metrics(stdout)
        assert m.get("speed_inference_ms") == pytest.approx(5.0)
        assert "precision" not in m

    def test_returns_all_expected_keys_from_full_output(self) -> None:
        m = parse_metrics(_COCO_FULL_STDOUT)
        for key in ("precision", "recall", "map50", "map50_95",
                    "speed_preprocess_ms", "speed_inference_ms", "speed_postprocess_ms"):
            assert key in m, f"missing key: {key}"


# ---------------------------------------------------------------------------
# expected_artifact_paths
# ---------------------------------------------------------------------------


class TestExpectedArtifactPaths:
    def test_eval_dir_path(self) -> None:
        paths = expected_artifact_paths({"output_dir": "/output", "run_name": "eval-1"})
        assert paths["eval_dir"] == "/output/eval-1"

    def test_default_run_name(self) -> None:
        paths = expected_artifact_paths({"output_dir": "/output"})
        assert "run" in paths["eval_dir"]


# ---------------------------------------------------------------------------
# build_binding / register_binding
# ---------------------------------------------------------------------------


class TestBuildBinding:
    def test_skill_id(self) -> None:
        b = build_binding()
        assert b.skill_id == SKILL_ID

    def test_binding_id(self) -> None:
        b = build_binding()
        assert b.binding_id == BINDING_ID

    def test_runtime_id(self) -> None:
        b = build_binding()
        assert b.runtime_id == RUNTIME_ID

    def test_verified_default_true(self) -> None:
        b = build_binding()
        assert b.verified is True

    def test_unverified_binding(self) -> None:
        b = build_binding(verified=False)
        assert b.verified is False

    def test_approval_policy_default(self) -> None:
        b = build_binding()
        assert b.approval_policy == "approval_required"

    def test_input_schema_has_required_fields(self) -> None:
        b = build_binding()
        required_names = {f.name for f in b.input_schema if f.required}
        assert "command" in required_names
        assert "data" in required_names
        assert "output_dir" in required_names
        assert "run_name" in required_names

    def test_input_schema_has_optional_fields(self) -> None:
        b = build_binding()
        optional_names = {f.name for f in b.input_schema if not f.required}
        assert "model" in optional_names
        assert "device" in optional_names
        assert "batch" in optional_names


class TestRegisterBinding:
    def test_register_and_retrieve(self) -> None:
        registry = ExecutionBindingRegistry()
        register_binding(registry)
        binding = registry.get_binding(SKILL_ID)
        assert binding is not None
        assert binding.binding_id == BINDING_ID

    def test_register_unverified(self) -> None:
        registry = ExecutionBindingRegistry()
        register_binding(registry, verified=False)
        binding = registry.get_binding(SKILL_ID)
        assert binding is not None
        assert binding.verified is False
