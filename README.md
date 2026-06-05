# Hunyuan3D-2 + 3D Print Pipeline

Генерация 3D-моделей из изображений с последующей подготовкой к 3D-печати.

Оригинальный репозиторий: [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2)

## Что такое Hunyuan3D-2

AI-модель от Tencent для генерации 3D-мешей с текстурами из одного изображения. Двухэтапный пайплайн:

1. **Shape generation** (Hunyuan3D-DiT) — создаёт геометрию меша из картинки
2. **Texture synthesis** (Hunyuan3D-Paint) — генерирует текстуру для меша

Требования: NVIDIA GPU с CUDA (6 GB VRAM только форма, 16 GB VRAM форма + текстура), Python 3.10+.

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

```bash
# Зависимости
pip install -r requirements.txt
pip install -e .

# C++/CUDA расширения для текстурирования
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
