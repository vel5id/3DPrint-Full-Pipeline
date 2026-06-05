# 3DPrint-Full-Pipeline — Blackwell Edition

Генерация 3D-моделей из изображений с последующей подготовкой к 3D-печати.
Форк [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2), проверен на видеокартах **RTX 50-series (Blackwell / sm_120)**.

[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://www.python.org/)
[![CUDA](https://img.shields.io/badge/CUDA-13.0-green?logo=nvidia)](https://developer.nvidia.com/cuda-toolkit)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.11%2Bcu130-orange?logo=pytorch)](https://pytorch.org/)
[![GPU](https://img.shields.io/badge/GPU-RTX%2050%20series%20%28sm__120%29-76b900?logo=nvidia)](https://www.nvidia.com/)
[![diffusers](https://img.shields.io/badge/diffusers-0.38.0-yellow)](https://github.com/huggingface/diffusers)
[![VRAM](https://img.shields.io/badge/VRAM-16%20GB-informational)]()

---

## Протестированное окружение

| Компонент | Версия / значение |
|---|---|
| GPU | NVIDIA RTX 5060 Ti (Blackwell, **sm_120**) |
| VRAM | 16 GB |
| CUDA | **13.0** (torch build: `cu130`) |
| Python | **3.12** |
| PyTorch | **2.11.0+cu130** |
| diffusers | 0.38.0 |
| transformers | 5.8.0 |
| ОС | Ubuntu 24.04 (WSL2) |

> **Почему Blackwell отдельно?** Архитектура sm_120 появилась в RTX 50‑й серии.
> Upstream Hunyuan3D-2 не запускается «из коробки»: оригинальные инструкции предполагают CUDA ≤12 и Python 3.10.
> Этот форк содержит исправления и инструкцию по сборке CUDA‑расширений для CUDA 13 / sm_120.

## Что такое Hunyuan3D-2

AI-модель от Tencent для генерации 3D-мешей с текстурами из одного изображения. Двухэтапный пайплайн:

1. **Shape generation** (Hunyuan3D-DiT) — создаёт геометрию меша из картинки
2. **Texture synthesis** (Hunyuan3D-Paint) — генерирует текстуру для меша

Требования: NVIDIA GPU с CUDA. VRAM: 6 GB (только форма), 16 GB (форма + текстура).
Этот форк протестирован на **Python 3.12 + CUDA 13.0 + PyTorch 2.11+cu130** (RTX 50-series).

## Что добавлено по сравнению с оригиналом

### 1. Part Decomposition (P3-SAM + XPart)

Автоматическая сегментация меша на смысловые части и генерация завершённых деталей:

- **P3-SAM** — сегментирует меш на части (корпус, крылья, колёса и т.д.)
- **XPart** — генерирует завершённые геометрии для каждой части (заполняет скрытые/отрезанные поверхности)

Работает прямо в Gradio UI: кнопки **"1. Segment Parts"** → **"2. Generate Parts"**.

### 2. 3D Print Preparation (Slicer)

Подготовка сгенерированных частей к FDM-печати:

- Проверка вписывания деталей в область печати
- Генерация pin/hole соединителей между соседними частями
- Экспорт STL-файлов, готовых к слайсингу
- ZIP-архив со всеми STL + README с инструкцией по сборке

Поддерживаемые профили принтеров: Qidi Q2, Ender 3, Prusa MK4.

В Gradio UI: кнопка **"3. Prepare for Printing"**.

### 3. Улучшения Gradio UI

- **Model Manager** (`gradio_model_manager.py`) — переключение моделей (v2.0, v2mini, v2mv, v2.1) без перезапуска
- **Live progress** — все длительные GPU-операции показывают статус в реальном времени (фазы очистки памяти, загрузки моделей, инференса, сохранения)
- **Memory management** — агрессивная очистка GPU/CPU памяти между этапами пайплайна, защита от OOM

### 4. Исправления утечек памяти

- P3-SAM: удаление GPU-тензоров после каждого батча (экономия ~1.6 GB/итерацию)
- XPart: выгрузка моделей с GPU между этапами
- Тройной `gc.collect()` + `empty_cache()` между стадиями пайплайна

## Установка

### 1. Зависимости

```bash
pip install -r requirements.txt
pip install -e .
```

### 2. CUDA-расширения для текстурирования

> **RTX 50-series (Blackwell / sm_120):** стандартная инструкция не работает — системный `nvcc` (CUDA 12) не поддерживает sm_120 и конфликтует с PyTorch cu130.
> Следуйте инструкции ниже.

#### Подготовка CUDA 13 toolchain (один раз, без sudo)

```bash
# Скачать nvcc 13 + заголовки CUDA 13 в ~/cuda13
BASE=https://developer.download.nvidia.com/compute/cuda/redist
mkdir -p ~/cuda13/dl && cd ~/cuda13/dl

# Скачать нужные компоненты
for PKG in cuda_nvcc cuda_cudart cuda_crt libnvvm cuda_cccl; do
    REL=$(python3 -c "import json,urllib.request; \
        d=json.loads(urllib.request.urlopen('$BASE/redistrib_13.0.2.json').read()); \
        print(d['$PKG']['linux-x86_64']['relative_path'])")
    curl -fSL -o ${PKG}.tar.xz "$BASE/$REL"
    tar xf ${PKG}.tar.xz
done

# Объединить в ~/cuda13
for DIR in cuda_nvcc-* cuda_cudart-* cuda_crt-* libnvvm-* cuda_cccl-*; do
    cp -a $DIR/. ~/cuda13/
done
cd ~/cuda13
[ -d lib64 ] || ln -s lib lib64

# Шимы хост-компилятора (gcc-12 обязателен — gcc-13 не поддерживается CUDA 13)
mkdir -p ~/cuda13/hostbin
ln -sf /usr/bin/gcc-12  ~/cuda13/hostbin/gcc
ln -sf /usr/bin/g++-12  ~/cuda13/hostbin/g++
```

Убедиться, что всё готово:
```bash
~/cuda13/bin/nvcc --version  # должно показать "release 13.0"
gcc-12 --version             # должно показать "gcc (Ubuntu 12.x...)"
```

#### Сборка custom_rasterizer

```bash
cd hy3dgen/texgen/custom_rasterizer

export CUDA_HOME=~/cuda13
export PATH=$CUDA_HOME/bin:$HOME/cuda13/hostbin:$PATH
export CC=gcc-12 CXX=g++-12
export TORCH_CUDA_ARCH_LIST="12.0"   # sm_120 = RTX 5060 Ti / 5070 / 5080 / 5090

rm -rf build custom_rasterizer.egg-info dist
pip install . --user --break-system-packages --no-build-isolation
cd ../../..
```

#### Сборка differentiable_renderer (опционально, есть Python-fallback)

```bash
cd hy3dgen/texgen/differentiable_renderer
export CUDA_HOME=~/cuda13
export PATH=$CUDA_HOME/bin:$HOME/cuda13/hostbin:$PATH
export CC=gcc-12 CXX=g++-12
pip install . --user --break-system-packages --no-build-isolation
cd ../../..
```

> После сборки `CUDA_HOME`/`PATH` **не нужны** для запуска — тулчейн нужен только при компиляции.

#### Для не-Blackwell GPU (RTX 40-series и старше, CUDA ≤12)

```bash
# Оригинальные инструкции upstream:
cd hy3dgen/texgen/custom_rasterizer && python setup.py install && cd ../../..
cd hy3dgen/texgen/differentiable_renderer && python setup.py install && cd ../../..
```

## Запуск

### Gradio Web UI

```bash
# Быстрый старт (mini модель, turbo)
python gradio_app.py \
  --model_path tencent/Hunyuan3D-2mini \
  --subfolder hunyuan3d-dit-v2-mini-turbo \
  --enable_flashvdm --low_vram_mode

# Полный пайплайн с текстурами
python gradio_app.py \
  --model_path tencent/Hunyuan3D-2 \
  --subfolder hunyuan3d-dit-v2-0-turbo \
  --enable_flashvdm --low_vram_mode
```

Открыть в браузере: `http://0.0.0.0:8080`

### CLI (только slicer)

```bash
python -m hy3dgen.slicer input.glb --profile qidi_q2 -o ./print_parts/
python -m hy3dgen.slicer parts/ -p ender3 --skip-connectors -v
```

### End-to-end демо

```bash
python examples/slicer_demo.py --image car.jpg --output ./car_parts/
```

## Пайплайн в Web UI

```
Изображение → Gen Shape → [Gen Textured Shape]
     → 1. Segment Parts (P3-SAM)
     → 2. Generate Parts (XPart)
     → 3. Prepare for Printing (Slicer)
     → ⬇️ Скачать ZIP со STL-файлами
```

## API (Python)

```python
# Генерация формы
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    'tencent/Hunyuan3D-2', subfolder='hunyuan3d-dit-v2-0-turbo'
)
mesh = pipeline(image='image.png', num_inference_steps=5)[0]

# Текстурирование
from hy3dgen.texgen import Hunyuan3DPaintPipeline
tex = Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2')
textured_mesh = tex(mesh, image='image.png')

# Сегментация частей
from hy3dgen.partseg import PartSegManager
mgr = PartSegManager()
aabb, face_ids = mgr.segment(mesh, seed=42)
parts_mesh, bbox_mesh, exploded = mgr.generate_parts("mesh.glb", aabb, seed=42)

# Подготовка к печати
from hy3dgen.slicer import SlicerManager
slicer = SlicerManager()
result = slicer.process(parts_mesh, output_dir="./stl/")
```

## Структура проекта (новые модули)

```
hy3dgen/
├── partseg/         # 🆕 P3-SAM + XPart: сегментация и генерация частей
├── slicer/          # 🆕 Подготовка к 3D-печати
│   ├── config.py    #   Профили принтеров (Qidi Q2, Ender 3, Prusa MK4)
│   ├── cutter.py    #   Проверка размеров деталей
│   ├── connectors.py#   Pin/hole генератор для сборки
│   └── memory.py    #   Мониторинг памяти
├── shapegen/        # Оригинальный shape generation
├── texgen/          # Оригинальный texture generation
└── rembg.py         # Удаление фона

P3-SAM/             # 🆕 Модель сегментации частей
XPart/              # 🆕 Модель завершения геометрии частей
hy3dshape/          # 🆕 Альтернативный shape generation (v2.1)
tests/              # 🆕 Тесты (44 теста)
```

## Благодарности

Оригинальный проект: [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2).

## BibTeX

```bibtex
@misc{hunyuan3d22025tencent,
    title={Hunyuan3D 2.0: Scaling Diffusion Models for High Resolution Textured 3D Assets Generation},
    author={Tencent Hunyuan3D Team},
    year={2025},
    eprint={2501.12202},
    archivePrefix={arXiv},
    primaryClass={cs.CV}
}
```
