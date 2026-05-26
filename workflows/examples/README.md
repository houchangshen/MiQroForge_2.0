# Sweep / Fan-Out / Fan-In 使用指南

## 概览

MF 工作流支持对单个节点进行**参数扫描（sweep）**：把同一个节点用不同的输入值并行执行多次，再将结果汇总到下游节点。这是通过 Argo Workflow 的 `withParam` 机制实现的，编译器会自动处理扇出和汇聚。

```
[geom-input] ← sweep (withParam)
       ↓
 [sp-calc]    ← auto fan-out (被 sweep 传播)
       ↓
[collect-energy]  ← fan-in (收集所有扫掠结果)
```

---

## 在哪里设置 sweep

在 MF YAML 的节点定义中加入 `parallel_sweep` 字段：

```yaml
nodes:
  - id: my-sweep-node
    node: some-node-spec           # 引用节点库中的正式节点
    parallel_sweep:
      values: [1.0, 1.2, 1.5, 2.0]  # 每个元素是一次执行的参数
    onboard_params:
      some_param: "{{item}}"        # {{item}} 会被替换为 values 中的值
```

### 关键字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `parallel_sweep.values` | `list[any]` | 扫描值列表，长度 >= 1。编译时生成 JSON array 作为 Argo 的 `withParam` |
| `{{item}}` | template | 在 `onboard_params` 的值中使用，运行时被替换为当前扫描值 |

### 注意事项

- `parallel_sweep` **不能**与 `ephemeral: true` 同时使用（临时节点不支持扇出）
- `values` 中的元素可以是数字、字符串等基本类型
- 同一个 MF YAML 中可以有多个 sweep 节点（多个独立的扫描链）

---

## 前端操作：Sweep 模式

在前端画布中，支持 `multiple_input` 的参数会显示一个 **⚡ Sweep** 按钮。点击后进入 Sweep 模式，显示两个字段：

### Values（扫描值列表）

每行一个值（或逗号分隔），驱动 `parallel_sweep.values`。例如：

```
0.5
0.6
0.7
```

### Pattern（模板表达式）

一个包含 `{{item}}` 的表达式，驱动 `onboard_params` 中的实际值。`{{item}}` 在运行时会被替换为当前扫描值。

- **默认值**：`{{item}}`（即直接用值本身）
- **文件模板示例**：`h2_{{item}}.xyz` → 运行时生成 `h2_0.5.xyz`、`h2_0.6.xyz` 等
- **前缀/后缀示例**：`mol_${item}_opt.xyz` 也可以自由组合

### 导出效果

使用 Values `0.5, 0.6, 0.7` + Pattern `h2_{{item}}.xyz` 导出的 YAML：

```yaml
parallel_sweep:
  values: [0.5, 0.6, 0.7]
onboard_params:
  geometry_file: "h2_{{item}}.xyz"
```

重新导入该 YAML 后，Values 和 Pattern 字段会正确恢复。

---

## Fan-Out 传播规则

Sweep 节点下游的直接依赖节点会**自动传播（auto fan-out）**：这些节点也会被编译到同一个 sweep pipeline 中，为每个值执行一次。

**传播规则：**
- Sweep 节点的直接下游（通过 Stream I/O 连接的节点）自动加入 sweep 链
- 如果下游的下游也是计算节点，继续传播
- 传播遇到以下情况时**停止**：
  - 该节点被显式标记为 `fan_in: true`
  - 该节点没有被 sweep 链中任何节点的 Stream Output 连接
  - 该节点是 DAG 的叶子节点且不需要参与 sweep

**示例：**
```yaml
nodes:
  - id: sweep-input
    node: geometry-file-input
    parallel_sweep:
      values: [0.5, 0.6, 0.7, 0.8]
    onboard_params:
      geometry_file: "mol_{{item}}.xyz"

  - id: calc-step        # ← 自动 fan-out（sweep-input 的下游）
    node: orca-single-point

  - id: collect-result   # ← fan-in（接收所有 sweep 结果）
    ephemeral: true
    ...
```

上面的例子中，`sweep-input` 和 `calc-step` 都会在 sweep pipeline 中执行（每个距离值一个实例），而 `collect-result` 在外部收集结果。

---

## Fan-In 汇聚

当 sweep 链的输出被非 sweep 链中的节点消费时，就是 **fan-in**（汇聚）。

### 自动生成的 fan-in

只要 sweep 节点的 Stream Output 端口连接到了 sweep 链**外部**的节点，编译器就会自动构建 fan-in 聚合。Fan-in 节点看到的输入是**所有扫掠实例的输出拼接后的列表**。

### 显式 fan-in 标记

你也可以显式将一个节点标记为 fan-in 收集点，防止它被 sweep 传播：

```yaml
nodes:
  - id: collector
    node: some-node
    fan_in: true     # 显式 fan-in，不参与 sweep 传播
```

### Ephemeral fan-in（最常见的 fan-in 方式）

临时节点天然适合作为 fan-in 收集点：它接收所有扫掠实例的 Stream 输出，在 Python 脚本中自行处理数据聚合（如列表求和、画图、生成报告）。

```yaml
nodes:
  - id: collect-energy
    ephemeral: true
    onboard_params:
      description: >-
        收集所有扫描点的单点能量，绘制势能曲线，
        输出 PNG 图片到 workspace/pes_plot.png。
    ports:
      inputs:
        - name: I1
          type: physical_quantity    # 接收扫掠节点的输出
      outputs:
        - name: O1
          type: report_object

connections:
  - from: calc-step.total_energy
    to: collect-energy.I1
```

---

## 编译策略：嵌套 DAG Pipeline

编译器将 sweep 链编译为**嵌套的 Argo DAG 模板（Pipeline Template）**：

```
外层 DAG:
  [sweep-pipeline-{id}]  ← withParam: 扫描值列表
         ↓ (fan-in)
  [downstream-node]

Pipeline 内层 DAG（每个值一个实例）:
  [sweep-input (item=0.5)] → [calc-step] → [输出转发]
  [sweep-input (item=0.6)] → [calc-step] → [输出转发]
  ...
```

每个扫描值的子工作流**独立异步执行**，没有跨实例的同步屏障。

### Quality Gate 在 Sweep 中的行为

Quality gate 在**嵌套 DAG 内部**正常工作，操作的是标量值（不是聚合后的数组）：

- `must_pass`（默认）：gate 不通过时，该实例的后续节点跳过，实例标记为失败
- `warn`：gate 不通过时发出警告，实例继续执行
- `ignore`：完全忽略 gate 检查

质量门控策略通过 `quality_policy` 字段覆盖：

```yaml
quality_policy:
  - node_id: geo-opt
    gate_name: converged
    action: warn        # 改为 warn，不通过只警告
```

Pipeline 输出参数带有 `default: ""`，因此个别实例被 gate 跳过不会导致下游 fan-in 节点因缺值而报错。

---

## 完整示例：H₂ 势能曲线扫描

```yaml
mf_version: "1.0"
name: h2-pes-sweep
description: H₂ 分子势能曲线扫描

nodes:
  # 12 个不同 H-H 距离，逐个读取 xyz 文件
  - id: geom-input
    node: geometry-file-input
    parallel_sweep:
      values: [0.5, 0.6, 0.7, 0.74, 0.742, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0, 3.0]
    onboard_params:
      geometry_file: "h2_{{item}}.xyz"

  # 每个距离的单点能计算（auto fan-out）
  - id: sp-calc
    node: orca-single-point
    onboard_params:
      charge: 0
      multiplicity: 1
      method: B3LYP
      basis_set: def2-SVP
      dispersion: D3BJ
      n_cores: 4

  # Fan-in：收集能量，绘制势能曲线
  - id: collect-energy
    ephemeral: true
    onboard_params:
      description: >-
        收集所有 H-H 距离扫描点的单点能量，绘制势能曲线（PES），
        输出 PNG 图片到 workspace/pes_plot.png。
      image_output: pes_plot.png
    ports:
      inputs:
        - name: I1
          type: physical_quantity
      outputs:
        - name: O1
          type: software_data_package

connections:
  - from: geom-input.xyz_geometry
    to: sp-calc.xyz_geometry
  - from: sp-calc.total_energy
    to: collect-energy.I1
```

### 编译和运行

```bash
# 校验
bash scripts/mf2.sh validate workflows/examples/h2-pes-sweep-mf.yaml

# 编译为 Argo YAML（查看嵌套 DAG 结构）
bash scripts/mf2.sh compile workflows/examples/h2-pes-sweep-mf.yaml

# 提交到集群
bash scripts/mf2.sh run workflows/examples/h2-pes-sweep-mf.yaml
```

编译后的 Argo YAML 会包含：
- 一个外层 DAG task `sweep-pipeline-geom-input`，带 `withParam` 引用扫描值 JSON
- 一个内层 Pipeline 模板，包含 `geom-input` 和 `sp-calc` 的执行逻辑
- 一个 fan-in 连接，将所有实例的 `total_energy` 汇聚到 `collect-energy`
- 前端 Runs 面板中，sweep 节点会显示为**带进度条的分组**（绿色=完成、蓝色=运行中、红色=失败），可展开查看每个实例的状态
