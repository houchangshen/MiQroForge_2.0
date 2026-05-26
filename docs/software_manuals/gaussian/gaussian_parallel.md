# Gaussian 16 Parallel Computing

## Overview

Gaussian 16 supports shared-memory parallelism on multi-core systems. Parallel execution is controlled through Link 0 commands that specify processor count, memory allocation, and scratch file management.

## Processor Specification

### %NProc=N

Specifies the total number of processors for the job.

```
%NProc=8
```

### %NProcShared=N

Specifies the number of shared-memory processors. This is the recommended way to specify parallel execution on a single node.

```
%NProcShared=4
```

### Differences Between %NProc and %NProcShared

- `%NProc`: Total processors, including those for Linda parallelism
- `%NProcShared`: Shared-memory processors on a single node
- For single-node jobs, both are equivalent
- For multi-node Linda jobs, use `%NProcShared` per node and `%NProc` for total

## Memory Specification

### %Mem=N

Total memory allocation for the job. Can specify in various units:

```
%Mem=1GB        # 1 gigabyte
%Mem=500MB      # 500 megabytes
%Mem=1024KB     # 1024 kilobytes
%Mem=500MW      # 500 megawords (1 MW = 8 MB)
%Mem=1GB        # 1 gigabyte
```

### Memory Guidelines

- **Minimum**: ~100 MB per processor for small calculations
- **Recommended**: 1-4 GB per processor for typical DFT calculations
- **Large calculations**: 8-32 GB total for systems with >500 basis functions
- **In-core SCF**: Requires enough memory to store all integrals

### Memory Sharing

Memory is shared among all processors. With `%NProcShared=4` and `%Mem=8GB`, each processor effectively has 2 GB available, but memory pools are shared dynamically.

## Scratch File Management

### %RWF=path

Specifies the read-write file location and optional size limits:

```
%RWF=/scratch/rwf,8GB
%RWF=/local/tmp/rwf
```

### %NoSave

Prevents saving the checkpoint file at the end of the job. Useful for intermediate steps.

```
%NoSave
```

### %Save

Forces saving all scratch files at the end of the job.

### %Chk=filename

Specifies the checkpoint file:

```
%Chk=water_b3lyp.chk
```

### %OldChk=filename

Specifies a previous checkpoint file for reading:

```
%OldChk=previous_calc.chk
```

## Shared-Memory Parallelism

Gaussian 16 uses shared-memory parallelism (SMP) on a single node. All processors share the same memory space.

### How It Works

- Two-electron integral computation is distributed across processors
- Each processor computes a subset of integrals
- Results are combined in shared memory
- SCF iterations use parallel linear algebra

### Performance Scaling

| Basis Functions | 1 proc | 2 proc | 4 proc | 8 proc |
|----------------|--------|--------|--------|--------|
| 100 | 1.0x | 1.8x | 3.2x | 5.0x |
| 300 | 1.0x | 1.9x | 3.5x | 6.0x |
| 500 | 1.0x | 1.9x | 3.6x | 6.5x |
| 1000 | 1.0x | 1.9x | 3.7x | 7.0x |

Scaling depends on:
- Basis set size (larger = better scaling)
- Calculation type (SCF scales well, MP2 less so)
- Memory availability
- Disk I/O speed

### Optimal Processor Count

- **Small jobs** (<100 basis functions): 1-2 processors
- **Medium jobs** (100-500 basis functions): 2-8 processors
- **Large jobs** (>500 basis functions): 4-16+ processors
- **Diminishing returns**: Usually beyond 8-16 processors per node

## Distributed-Memory Parallelism (Linda)

Gaussian supports distributed-memory parallelism through Linda for multi-node calculations.

### Linda Configuration

```
%NProcShared=8    # 8 processors per node
%NProc=32         # 32 total processors (4 nodes)
```

### Linda Limitations

- Requires Linda license
- Not all calculation types support Linda
- Communication overhead can limit scaling
- Best for large calculations with many basis functions

## GPU Acceleration

Gaussian 16 supports GPU acceleration for certain operations.

### GPU Requirements

- NVIDIA GPU with CUDA support
- Sufficient GPU memory
- Compatible GPU driver

### GPU Usage

GPU acceleration is automatic for supported operations:
- Two-electron integral computation
- SCF iterations
- Some post-SCF methods

### GPU Memory

GPU memory is separate from CPU memory. Ensure sufficient GPU memory for the calculation.

## Performance Tuning

### Memory Optimization

1. **Increase %Mem**: More memory = less disk I/O
2. **In-core SCF**: `SCF=InCore` if enough memory
3. **Avoid swapping**: Ensure physical memory exceeds %Mem

### Disk I/O Optimization

1. **Use fast local storage**: SSD or NVMe for scratch files
2. **Avoid network storage**: Local scratch directories perform better
3. **Increase %RWF space**: Prevents intermediate file overflow

### Processor Optimization

1. **Match physical cores**: Don't exceed physical core count
2. **Avoid hyperthreading oversubscription**: Use physical cores, not logical
3. **NUMA awareness**: On multi-socket systems, consider NUMA topology

### Calculation-Specific Tips

#### SCF Calculations

- Direct SCF (`SCF=Direct`, default) scales well
- In-core SCF (`SCF=InCore`) faster if enough memory
- Conventional SCF (`SCF=Conventional`) for small systems with enough disk

#### Post-SCF Calculations

- MP2: Scales reasonably well
- CCSD: Limited parallel scaling
- CCSD(T): Memory intensive, good scaling for integral computation

#### Frequency Calculations

- Analytical frequencies scale well
- Numerical frequencies: Each displacement independent (embarrassingly parallel)

## Example Parallel Job

### Basic Parallel Job

```
%NProcShared=8
%Mem=16GB
%Chk=water.chk
\# B3LYP/6-311+G(d,p) Opt Freq Pop=Full

Water optimization and frequency

0 1
O  0.0  0.0  0.0
H  0.0  0.0  0.96
H  0.0  0.96  0.0
```

### Large Calculation with Memory Management

```
%NProcShared=16
%Mem=64GB
%RWF=/local/scratch/rwf,100GB
%Chk=large_mol.chk
\# B3LYP/6-31G(d) SCF=(InCore,MaxCycle=256) Opt=(CalcFC,MaxCycle=100)

Large molecule optimization

0 1
[large molecule coordinates]
```

### Multi-Step Job with Checkpoint

```
%NProcShared=8
%Mem=32GB
%Chk=step1.chk
\# B3LYP/6-31G(d) Opt Freq

Step 1: Optimize and frequencies

0 1
[molecule]

--Link1--
%NProcShared=8
%Mem=32GB
%OldChk=step1.chk
%Chk=step2.chk
\# B3LYP/6-311+G(d,p) Geom=Check Guess=Read Pop=Full

Step 2: Single point with larger basis

0 1
```

## Troubleshooting

### Slow Performance

1. Check if memory is sufficient (`%Mem`)
2. Verify processor count matches physical cores
3. Use local scratch directory
4. Check for disk I/O bottlenecks

### Memory Errors

```
Insufficient memory.
```

- Increase `%Mem`
- Reduce `%NProcShared`
- Use `SCF=Conventional` instead of in-core

### Disk Space Errors

```
Write error in NtrExt1.
```

- Increase `%RWF` space
- Clean scratch directory
- Use `%NoSave` for intermediate steps

### Poor Parallel Scaling

- Reduce processor count
- Check NUMA topology
- Use `SCF=InCore` if possible
- Consider calculation type limitations
