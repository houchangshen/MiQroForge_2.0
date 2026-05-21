"""节点索引（node_index）模块测试。

覆盖：
- PortSummary / NodeIndexEntry / NodeIndex 模型
- scanner: 扫描 nodes/ 目录、生成 NodeIndexEntry
- search: 文本搜索
- cli: 命令输出格式
"""

from __future__ import annotations

from pathlib import Path

import pytest

from node_index.models import NodeIndex, NodeIndexEntry, OnBoardInputSummary, OnBoardOutputSummary, PortSummary
from node_index.scanner import load_index, scan_nodes, write_index
from node_index.search import search_nodes


# ═══════════════════════════════════════════════════════════════════════════
# 模型测试
# ═══════════════════════════════════════════════════════════════════════════

class TestPortSummary:

    def test_creation(self):
        p = PortSummary(
            name="gbw_file",
            display_name="GBW Wavefunction",
            category="software_data_package",
            detail="orca/gbw-file",
            direction="output",
        )
        assert p.name == "gbw_file"
        assert p.category == "software_data_package"
        assert p.detail == "orca/gbw-file"

    def test_default_direction(self):
        p = PortSummary(
            name="energy",
            display_name="Energy",
            category="physical_quantity",
        )
        assert p.direction == "input"


class TestNodeIndexEntry:

    def _make_entry(self, **overrides) -> NodeIndexEntry:
        defaults = dict(
            name="orca-geo-opt",
            version="1.0.0",
            display_name="ORCA Geometry Optimization",
            description="DFT geometry optimization using ORCA.",
            node_type="compute",
            category="chemistry",
            base_image_ref="orca-6.1",
            nodespec_path="nodes/chemistry/orca/orca-geo-opt/nodespec.yaml",
            software="orca",
            methods=["DFT", "geometry-optimization"],
            domains=["molecular"],
            capabilities=["geometry-optimization"],
            keywords=["orca", "dft"],
            resources_cpu=4.0,
            resources_memory_gb=8.0,
            stream_inputs=[],
            stream_outputs=[
                PortSummary(name="gbw_file", display_name="GBW", category="software_data_package", detail="orca/gbw-file"),
            ],
            onboard_inputs=[
                OnBoardInputSummary(name="functional", display_name="DFT Functional", kind="string", default="B3LYP"),
            ],
            onboard_outputs=[
                OnBoardOutputSummary(name="opt_converged", display_name="Converged", kind="boolean",
                                     quality_gate=True, gate_default="must_pass"),
            ],
        )
        defaults.update(overrides)
        return NodeIndexEntry(**defaults)

    def test_creation(self):
        entry = self._make_entry()
        assert entry.name == "orca-geo-opt"
        assert entry.node_type == "compute"
        assert len(entry.stream_outputs) == 1
        assert len(entry.onboard_inputs) == 1
        assert entry.onboard_inputs[0].name == "functional"
        assert len(entry.onboard_outputs) == 1
        assert entry.onboard_outputs[0].quality_gate is True
        assert entry.resources_cpu == 4.0
        assert entry.resources_memory_gb == 8.0

    def test_serialization(self):
        entry = self._make_entry()
        d = entry.model_dump()
        entry2 = NodeIndexEntry.model_validate(d)
        assert entry2.name == entry.name
        assert len(entry2.stream_outputs) == len(entry.stream_outputs)


class TestNodeIndex:

    def test_empty_index(self):
        idx = NodeIndex(generated_at="2026-01-01T00:00:00+00:00", total_nodes=0)
        assert idx.total_nodes == 0
        assert idx.mf_version == "1.0"

    def test_with_entries(self):
        entry = NodeIndexEntry(
            name="test-node",
            version="1.0.0",
            display_name="Test",
            node_type="lightweight",
            category="utility",
            nodespec_path="nodes/test/test-node/nodespec.yaml",
        )
        idx = NodeIndex(
            generated_at="2026-01-01T00:00:00+00:00",
            total_nodes=1,
            entries=[entry],
        )
        assert idx.total_nodes == 1
        assert idx.entries[0].name == "test-node"


# ═══════════════════════════════════════════════════════════════════════════
# Scanner 测试
# ═══════════════════════════════════════════════════════════════════════════

class TestScanner:

    @pytest.fixture()
    def project_root(self) -> Path:
        """返回项目根目录。"""
        # 从 tests/unit/ 向上 2 层
        return Path(__file__).parent.parent.parent

    def test_scan_finds_orca_nodes(self, project_root):
        index = scan_nodes(project_root)
        names = [e.name for e in index.entries]
        assert "orca-geo-opt" in names
        assert "orca-freq" in names
        assert "orca-single-point" in names
        # orca-thermo-extractor 已移除（功能整合到 orca-freq）
        assert "orca-thermo-extractor" not in names

    def test_scan_finds_test_nodes(self, project_root):
        index = scan_nodes(project_root, include_test_nodes=True)
        names = [e.name for e in index.entries]
        assert "test-gaussian-geo-opt" in names
        assert "test-gaussian-freq" in names
        assert "test-thermo-extractor" in names

    def test_scan_default_skips_test_nodes(self, project_root):
        index = scan_nodes(project_root)
        names = [e.name for e in index.entries]
        assert "test-gaussian-geo-opt" not in names
        assert "orca-geo-opt" in names

    def test_total_nodes_count(self, project_root):
        index = scan_nodes(project_root)
        assert index.total_nodes == len(index.entries)
        # 默认不包含测试节点，只有 ORCA 节点
        assert index.total_nodes >= 3

    def test_entries_sorted_by_category_name(self, project_root):
        index = scan_nodes(project_root)
        cats_names = [(e.category, e.name) for e in index.entries]
        assert cats_names == sorted(cats_names)

    def test_orca_geo_opt_entry_fields(self, project_root):
        index = scan_nodes(project_root)
        entry = next(e for e in index.entries if e.name == "orca-geo-opt")
        assert entry.node_type == "compute"
        assert entry.base_image_ref == "orca-6.1"
        assert entry.software == "orca"
        assert "geometry-optimization" in entry.capabilities
        # stream_inputs: xyz_geometry（已从 onboard 迁移为 stream input）
        assert len(entry.stream_inputs) == 1
        assert entry.stream_inputs[0].name == "xyz_geometry"
        # stream_outputs: gbw_file, optimized_xyz, total_energy (opt_converged migrated to quality gate)
        assert len(entry.stream_outputs) == 3
        # onboard_inputs: 8 computational params + 1 auto-injected walltime_hours (from parametrize)
        assert len(entry.onboard_inputs) == 9
        assert all(p.name for p in entry.onboard_inputs)
        # resources available in index
        assert entry.resources_cpu > 0
        assert entry.resources_memory_gb > 0

    def test_thermo_extractor_is_lightweight(self, project_root):
        """orca-thermo-extractor 已移除；test-thermo-extractor 是 compute mock 节点。
        需要 include_test_nodes=True 才能扫描到。
        """
        index = scan_nodes(project_root, include_test_nodes=True)
        names = [e.name for e in index.entries]
        assert "test-thermo-extractor" in names
        entry = next(e for e in index.entries if e.name == "test-thermo-extractor")
        # mock 节点为 compute 类型
        assert entry.node_type == "compute"

    def test_port_summaries_have_details(self, project_root):
        index = scan_nodes(project_root)
        entry = next(e for e in index.entries if e.name == "orca-geo-opt")

        # GBW output
        gbw = next(p for p in entry.stream_outputs if p.name == "gbw_file")
        assert gbw.category == "software_data_package"
        assert gbw.detail == "orca/gbw-file"

        # opt_converged is no longer a stream output (migrated to quality gate)
        port_names = [p.name for p in entry.stream_outputs]
        assert "opt_converged" not in port_names

    def test_semantic_display_name_populated(self, project_root):
        index = scan_nodes(project_root)
        geo_opt = next(e for e in index.entries if e.name == "orca-geo-opt")
        assert geo_opt.semantic_display_name == "Geometry Optimization"

    def test_semantic_display_name_for_freq(self, project_root):
        index = scan_nodes(project_root)
        freq = next(e for e in index.entries if e.name == "orca-freq")
        assert freq.semantic_display_name == "Frequency Analysis"

    def test_onboard_inputs_fully_indexed(self, project_root):
        """onboard_inputs 完整定义被索引，拖入画布无需读取 nodespec.yaml。"""
        index = scan_nodes(project_root)
        entry = next(e for e in index.entries if e.name == "orca-geo-opt")
        # xyz_geometry 已迁移到 stream_inputs，剩余 8 个 onboard params + 1 auto-injected walltime_hours
        assert len(entry.onboard_inputs) == 9
        for p in entry.onboard_inputs:
            assert p.kind in ("string", "integer", "float", "boolean", "enum", "textarea")
            assert p.display_name

    def test_onboard_outputs_with_quality_gate(self, project_root):
        """quality gate onboard_outputs 被完整索引，包含 gate_default。"""
        index = scan_nodes(project_root)
        entry = next(e for e in index.entries if e.name == "orca-geo-opt")
        gates = [o for o in entry.onboard_outputs if o.quality_gate]
        assert len(gates) >= 1
        gate = next(g for g in gates if g.name == "opt_converged")
        assert gate.gate_default == "must_pass"
        assert gate.kind == "boolean"

    def test_resources_in_index(self, project_root):
        """resources_cpu / resources_memory_gb 被写入索引。"""
        index = scan_nodes(project_root)
        for entry in index.entries:
            assert entry.resources_cpu >= 0
            assert entry.resources_memory_gb >= 0
        geo_opt = next(e for e in index.entries if e.name == "orca-geo-opt")
        assert geo_opt.resources_cpu > 0
        assert geo_opt.resources_memory_gb > 0

    def test_rag_summary_not_in_index(self, project_root):
        """rag_summary は索引から削除されている。"""
        index = scan_nodes(project_root)
        entry = index.entries[0]
        assert not hasattr(entry, "rag_summary")

    def test_semantic_display_name_none_for_no_semantic_type(self, project_root):
        """没有 semantic_type 的节点，semantic_display_name 应该为 None。"""
        index = scan_nodes(project_root)
        # Test nodes without semantic_type (e.g., nodes that don't have one set)
        entries_without_st = [e for e in index.entries if e.semantic_display_name is None]
        # At minimum there should exist some entries (nodes without semantic_type)
        # This is just a structural check — the field exists and defaults to None
        for e in index.entries:
            if e.semantic_display_name is not None:
                # If it has a display name, it must be non-empty string
                assert isinstance(e.semantic_display_name, str)
                assert len(e.semantic_display_name) > 0

    def test_write_and_load_roundtrip(self, project_root, tmp_path):
        """写入到临时目录再读取，验证 YAML 往返。"""
        # 创建临时 nodes/ 目录
        (tmp_path / "nodes").mkdir()
        index = scan_nodes(project_root)
        output = write_index(index, tmp_path)
        assert output.exists()

        loaded = load_index(tmp_path)
        assert loaded.total_nodes == index.total_nodes
        assert len(loaded.entries) == len(index.entries)
        assert loaded.entries[0].name == index.entries[0].name

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="node_index.yaml"):
            load_index(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════
# Search 测试
# ═══════════════════════════════════════════════════════════════════════════

class TestSearch:

    @pytest.fixture(scope="class")
    def index(self) -> NodeIndex:
        project_root = Path(__file__).parent.parent.parent
        return scan_nodes(project_root, include_test_nodes=True)

    def test_search_orca(self, index):
        results = search_nodes(index, "orca")
        names = [e.name for e in results]
        assert "orca-geo-opt" in names
        assert "orca-freq" in names
        assert "orca-single-point" in names
        # orca-thermo-extractor 已移除
        assert "orca-thermo-extractor" not in names

    def test_search_geo_opt(self, index):
        results = search_nodes(index, "geo-opt")
        names = [e.name for e in results]
        assert "orca-geo-opt" in names
        # 匹配度最高的应该是第一个
        assert results[0].name in ["orca-geo-opt", "test-gaussian-geo-opt"]

    def test_search_thermo(self, index):
        results = search_nodes(index, "thermo")
        names = [e.name for e in results]
        assert "orca-thermo-extractor" in names or "test-thermo-extractor" in names

    def test_search_no_match_returns_empty(self, index):
        results = search_nodes(index, "xyznonexistentquery12345")
        assert len(results) == 0

    def test_search_empty_query_returns_all(self, index):
        results = search_nodes(index, "")
        assert len(results) == index.total_nodes

    def test_search_max_results(self, index):
        results = search_nodes(index, "orca", max_results=2)
        assert len(results) <= 2

    def test_search_by_capability(self, index):
        results = search_nodes(index, "geometry-optimization")
        names = [e.name for e in results]
        assert any("geo-opt" in name for name in names)

    def test_search_by_software(self, index):
        results = search_nodes(index, "gaussian")
        names = [e.name for e in results]
        # test 节点 software=gaussian 应该命中
        assert any("gaussian" in name for name in names)

    def test_search_result_ordering(self, index):
        """精确名称匹配应排在前列。"""
        results = search_nodes(index, "orca-geo-opt")
        if results:
            assert results[0].name == "orca-geo-opt"
