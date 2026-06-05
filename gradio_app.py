# Hunyuan 3D is licensed under the TENCENT HUNYUAN NON-COMMERCIAL LICENSE AGREEMENT
# except for the third-party components listed below.
# Hunyuan 3D does not impose any additional limitations beyond what is outlined
# in the repsective licenses of these third-party components.
# Users must comply with all terms and conditions of original licenses of these third-party
# components and must ensure that the usage of the third party components adheres to
# all relevant laws and regulations.

# For avoidance of doubts, Hunyuan 3D means the large language models and
# their software and algorithms, including trained model weights, parameters (including
# optimizer states), machine-learning model code, inference-enabling code, training-enabling code,
# fine-tuning enabling code and other elements of the foregoing made publicly available
# by Tencent in accordance with TENCENT HUNYUAN COMMUNITY LICENSE AGREEMENT.

import os
import random
import shutil
import time
from glob import glob
from pathlib import Path

import gradio as gr
import torch
import trimesh
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uuid

from hy3dgen.shapegen.utils import logger
from gradio_model_manager import (
    ModelManager,
    SHAPE_MODEL_CONFIGS,
    TEX_MODEL_CONFIGS,
    get_available_variants,
)

MAX_SEED = int(1e7)

# model_mgr is initialized in __main__ and used by all generator functions
model_mgr: ModelManager = None


def get_example_img_list():
    print('Loading example img list ...')
    return sorted(glob('./assets/example_images/**/*.png', recursive=True))


def get_example_txt_list():
    print('Loading example txt list ...')
    txt_list = list()
    for line in open('./assets/example_prompts.txt', encoding='utf-8'):
        txt_list.append(line.strip())
    return txt_list


def get_example_mv_list():
    print('Loading example mv list ...')
    mv_list = list()
    root = './assets/example_mv_images'
    for mv_dir in os.listdir(root):
        view_list = []
        for view in ['front', 'back', 'left', 'right']:
            path = os.path.join(root, mv_dir, f'{view}.png')
            if os.path.exists(path):
                view_list.append(path)
            else:
                view_list.append(None)
        mv_list.append(view_list)
    return mv_list


def gen_save_folder(max_size=200):
    os.makedirs(SAVE_DIR, exist_ok=True)

    # 获取所有文件夹路径
    dirs = [f for f in Path(SAVE_DIR).iterdir() if f.is_dir()]

    # 如果文件夹数量超过 max_size，删除创建时间最久的文件夹
    if len(dirs) >= max_size:
        # 按创建时间排序，最久的排在前面
        oldest_dir = min(dirs, key=lambda x: x.stat().st_ctime)
        shutil.rmtree(oldest_dir)
        print(f"Removed the oldest folder: {oldest_dir}")

    # 生成一个新的 uuid 文件夹名称
    new_folder = os.path.join(SAVE_DIR, str(uuid.uuid4()))
    os.makedirs(new_folder, exist_ok=True)
    print(f"Created new folder: {new_folder}")

    return new_folder


def export_mesh(mesh, save_folder, textured=False, type='glb'):
    if textured:
        path = os.path.join(save_folder, f'textured_mesh.{type}')
    else:
        path = os.path.join(save_folder, f'white_mesh.{type}')
    if type not in ['glb', 'obj']:
        mesh.export(path)
    else:
        mesh.export(path, include_normals=textured)
    return path


def randomize_seed_fn(seed: int, randomize_seed: bool) -> int:
    if randomize_seed:
        seed = random.randint(0, MAX_SEED)
    return seed


def build_model_viewer_html(save_folder, height=660, width=790, textured=False):
    # Remove first folder from path to make relative path
    if textured:
        related_path = f"./textured_mesh.glb"
        template_name = './assets/modelviewer-textured-template.html'
        output_html_path = os.path.join(save_folder, f'textured_mesh.html')
    else:
        related_path = f"./white_mesh.glb"
        template_name = './assets/modelviewer-template.html'
        output_html_path = os.path.join(save_folder, f'white_mesh.html')
    offset = 50 if textured else 10
    with open(os.path.join(CURRENT_DIR, template_name), 'r', encoding='utf-8') as f:
        template_html = f.read()

    with open(output_html_path, 'w', encoding='utf-8') as f:
        template_html = template_html.replace('#height#', f'{height - offset}')
        template_html = template_html.replace('#width#', f'{width}')
        template_html = template_html.replace('#src#', f'{related_path}/')
        f.write(template_html)

    rel_path = os.path.relpath(output_html_path, SAVE_DIR)
    iframe_tag = f'<iframe src="/static/{rel_path}" height="{height}" width="100%" frameborder="0"></iframe>'
    print(
        f'Find html file {output_html_path}, {os.path.exists(output_html_path)}, relative HTML path is /static/{rel_path}')

    return f"""
        <div style='height: {height}; width: 100%;'>
        {iframe_tag}
        </div>
    """


def _gen_shape(
    caption=None,
    image=None,
    mv_image_front=None,
    mv_image_back=None,
    mv_image_left=None,
    mv_image_right=None,
    steps=50,
    guidance_scale=7.5,
    seed=1234,
    octree_resolution=256,
    check_box_rembg=False,
    num_chunks=200000,
    randomize_seed: bool = False,
):
    if not model_mgr.is_mv_mode and image is None and caption is None:
        raise gr.Error("Please provide either a caption or an image.")
    if model_mgr.is_mv_mode:
        if mv_image_front is None and mv_image_back is None and mv_image_left is None and mv_image_right is None:
            raise gr.Error("Please provide at least one view image.")
        image = {}
        if mv_image_front:
            image['front'] = mv_image_front
        if mv_image_back:
            image['back'] = mv_image_back
        if mv_image_left:
            image['left'] = mv_image_left
        if mv_image_right:
            image['right'] = mv_image_right

    seed = int(randomize_seed_fn(seed, randomize_seed))

    octree_resolution = int(octree_resolution)
    if caption: print('prompt is', caption)
    save_folder = gen_save_folder()
    stats = {
        'model': {
            'shapegen': f'{model_mgr.current_repo}/{model_mgr.current_subfolder}',
            'texgen': f'{model_mgr.current_tex_display}',
        },
        'params': {
            'caption': caption,
            'steps': steps,
            'guidance_scale': guidance_scale,
            'seed': seed,
            'octree_resolution': octree_resolution,
            'check_box_rembg': check_box_rembg,
            'num_chunks': num_chunks,
        }
    }
    time_meta = {}

    if image is None:
        start_time = time.time()
        try:
            image = model_mgr.t2i_worker(caption)
        except Exception as e:
            raise gr.Error(f"Text to 3D is disable. Please enable it by `python gradio_app.py --enable_t23d`.")
        time_meta['text2image'] = time.time() - start_time

    # remove disk io to make responding faster, uncomment at your will.
    # image.save(os.path.join(save_folder, 'input.png'))
    if model_mgr.is_mv_mode:
        start_time = time.time()
        for k, v in image.items():
            if check_box_rembg or v.mode == "RGB":
                img = model_mgr.rmbg_worker(v.convert('RGB'))
                image[k] = img
        time_meta['remove background'] = time.time() - start_time
    else:
        if check_box_rembg or image.mode == "RGB":
            start_time = time.time()
            image = model_mgr.rmbg_worker(image.convert('RGB'))
            time_meta['remove background'] = time.time() - start_time

    # remove disk io to make responding faster, uncomment at your will.
    # image.save(os.path.join(save_folder, 'rembg.png'))

    # image to white model
    start_time = time.time()

    generator = torch.Generator()
    generator = generator.manual_seed(int(seed))

    if model_mgr.is_omni:
        # Omni pipeline: returns {'shapes': [mesh], ...}
        outputs = model_mgr.shape_pipeline(
            image=image,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
            octree_resolution=octree_resolution,
            num_chunks=num_chunks,
            output_type='trimesh',
        )
        time_meta['shape generation'] = time.time() - start_time
        logger.info("---Shape generation takes %s seconds ---" % (time.time() - start_time))
        tmp_start = time.time()
        mesh = outputs['shapes'][0]  # trimesh already
        time_meta['export to trimesh'] = time.time() - tmp_start
    else:
        outputs = model_mgr.shape_pipeline(
            image=image,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            generator=generator,
            octree_resolution=octree_resolution,
            num_chunks=num_chunks,
            output_type='mesh'
        )
        time_meta['shape generation'] = time.time() - start_time
        logger.info("---Shape generation takes %s seconds ---" % (time.time() - start_time))
        tmp_start = time.time()
        mesh = export_to_trimesh(outputs)[0]
        time_meta['export to trimesh'] = time.time() - tmp_start

    stats['number_of_faces'] = mesh.faces.shape[0]
    stats['number_of_vertices'] = mesh.vertices.shape[0]

    stats['time'] = time_meta
    main_image = image if not model_mgr.is_mv_mode else image['front']
    return mesh, main_image, save_folder, stats, seed


def generation_all(
    caption=None,
    image=None,
    mv_image_front=None,
    mv_image_back=None,
    mv_image_left=None,
    mv_image_right=None,
    steps=50,
    guidance_scale=7.5,
    seed=1234,
    octree_resolution=256,
    check_box_rembg=False,
    num_chunks=200000,
    randomize_seed: bool = False,
):
    start_time_0 = time.time()
    mesh, image, save_folder, stats, seed = _gen_shape(
        caption,
        image,
        mv_image_front=mv_image_front,
        mv_image_back=mv_image_back,
        mv_image_left=mv_image_left,
        mv_image_right=mv_image_right,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        octree_resolution=octree_resolution,
        check_box_rembg=check_box_rembg,
        num_chunks=num_chunks,
        randomize_seed=randomize_seed,
    )
    path = export_mesh(mesh, save_folder, textured=False)

    # tmp_time = time.time()
    # mesh = floater_remove_worker(mesh)
    # mesh = degenerate_face_remove_worker(mesh)
    # logger.info("---Postprocessing takes %s seconds ---" % (time.time() - tmp_time))
    # stats['time']['postprocessing'] = time.time() - tmp_time

    tmp_time = time.time()
    mesh = model_mgr.face_reducer(mesh)
    logger.info("---Face Reduction takes %s seconds ---" % (time.time() - tmp_time))
    stats['time']['face reduction'] = time.time() - tmp_time

    tmp_time = time.time()
    textured_mesh = model_mgr.tex_pipeline(mesh, image)
    logger.info("---Texture Generation takes %s seconds ---" % (time.time() - tmp_time))
    stats['time']['texture generation'] = time.time() - tmp_time
    stats['time']['total'] = time.time() - start_time_0

    textured_mesh.metadata['extras'] = stats
    path_textured = export_mesh(textured_mesh, save_folder, textured=True)
    model_viewer_html_textured = build_model_viewer_html(save_folder, height=HTML_HEIGHT, width=HTML_WIDTH,
                                                         textured=True)
    if model_mgr.low_vram_mode:
        torch.cuda.empty_cache()
    return (
        gr.update(value=path),
        gr.update(value=path_textured),
        model_viewer_html_textured,
        stats,
        seed,
    )


def shape_generation(
    caption=None,
    image=None,
    mv_image_front=None,
    mv_image_back=None,
    mv_image_left=None,
    mv_image_right=None,
    steps=50,
    guidance_scale=7.5,
    seed=1234,
    octree_resolution=256,
    check_box_rembg=False,
    num_chunks=200000,
    randomize_seed: bool = False,
):
    start_time_0 = time.time()
    mesh, image, save_folder, stats, seed = _gen_shape(
        caption,
        image,
        mv_image_front=mv_image_front,
        mv_image_back=mv_image_back,
        mv_image_left=mv_image_left,
        mv_image_right=mv_image_right,
        steps=steps,
        guidance_scale=guidance_scale,
        seed=seed,
        octree_resolution=octree_resolution,
        check_box_rembg=check_box_rembg,
        num_chunks=num_chunks,
        randomize_seed=randomize_seed,
    )
    stats['time']['total'] = time.time() - start_time_0
    mesh.metadata['extras'] = stats

    path = export_mesh(mesh, save_folder, textured=False)
    model_viewer_html = build_model_viewer_html(save_folder, height=HTML_HEIGHT, width=HTML_WIDTH)
    if model_mgr.low_vram_mode:
        torch.cuda.empty_cache()
    return (
        gr.update(value=path),
        model_viewer_html,
        stats,
        seed,
    )


def build_app():
    title = 'Hunyuan3D-2: High Resolution Textured 3D Assets Generation'
    if model_mgr.is_mv_mode:
        title = 'Hunyuan3D-2mv: Image to 3D Generation with 1-4 Views'
    if 'mini' in model_mgr.current_subfolder:
        title = 'Hunyuan3D-2mini: Strong 0.6B Image to Shape Generator'
    if model_mgr.is_turbo:
        title = title.replace(':', '-Turbo: Fast ')

    title_html = f"""
    <div style="font-size: 2em; font-weight: bold; text-align: center; margin-bottom: 5px">

    {title}
    </div>
    <div align="center">
    Tencent Hunyuan3D Team
    </div>
    <div align="center">
      <a href="https://github.com/tencent/Hunyuan3D-2">Github</a> &ensp; 
      <a href="http://3d-models.hunyuan.tencent.com">Homepage</a> &ensp;
      <a href="https://3d.hunyuan.tencent.com">Hunyuan3D Studio</a> &ensp;
      <a href="#">Technical Report</a> &ensp;
      <a href="https://huggingface.co/Tencent/Hunyuan3D-2"> Pretrained Models</a> &ensp;
    </div>
    """
    custom_css = """
    .app.svelte-wpkpf6.svelte-wpkpf6:not(.fill_width) {
        max-width: 1480px;
    }
    .mv-image button .wrap {
        font-size: 10px;
    }

    .mv-image .icon-wrap {
        width: 20px;
    }

    """

    with gr.Blocks(theme=gr.themes.Base(), title='Hunyuan-3D-2.0', analytics_enabled=False, css=custom_css) as demo:
        gr.HTML(title_html)

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Column():
                    with gr.Accordion('Image Prompt', open=not model_mgr.is_mv_mode, visible=not model_mgr.is_mv_mode) as tab_ip:
                        image = gr.Image(label='Image', type='pil', image_mode='RGBA', height=290)

                    with gr.Accordion('Text Prompt', open=False, visible=HAS_T2I and not model_mgr.is_mv_mode) as tab_tp:
                        caption = gr.Textbox(label='Text Prompt',
                                             placeholder='HunyuanDiT will be used to generate image.',
                                             info='Example: A 3D model of a cute cat, white background')
                    with gr.Accordion('MultiView Prompt', open=model_mgr.is_mv_mode, visible=model_mgr.is_mv_mode) as tab_mv:
                        # gr.Label('Please upload at least one front image.')
                        with gr.Row():
                            mv_image_front = gr.Image(label='Front', type='pil', image_mode='RGBA', height=140,
                                                      min_width=100, elem_classes='mv-image')
                            mv_image_back = gr.Image(label='Back', type='pil', image_mode='RGBA', height=140,
                                                     min_width=100, elem_classes='mv-image')
                        with gr.Row():
                            mv_image_left = gr.Image(label='Left', type='pil', image_mode='RGBA', height=140,
                                                     min_width=100, elem_classes='mv-image')
                            mv_image_right = gr.Image(label='Right', type='pil', image_mode='RGBA', height=140,
                                                      min_width=100, elem_classes='mv-image')

                with gr.Row():
                    btn = gr.Button(value='Gen Shape', variant='primary', min_width=100)
                    btn_all = gr.Button(value='Gen Textured Shape',
                                        variant='primary',
                                        visible=HAS_TEXTUREGEN,
                                        min_width=100)

                with gr.Group():
                    file_out = gr.File(label="File", visible=False)
                    file_out2 = gr.File(label="File", visible=False)

                with gr.Column():
                    with gr.Accordion("Model Selection", open=True):
                        model_family = gr.Dropdown(
                            label="Shape Model",
                            choices=ModelManager.get_family_choices(),
                            value=model_mgr.shape_family,
                            interactive=True,
                        )
                        speed_variant = gr.Dropdown(
                            label="Speed Variant",
                            choices=get_available_variants(model_mgr.shape_family),
                            value=model_mgr.shape_variant,
                            interactive=True,
                        )
                        tex_model = gr.Dropdown(
                            label="Texture Model",
                            choices=ModelManager.get_tex_choices(),
                            value=model_mgr.tex_key,
                            interactive=True,
                            visible=HAS_TEXTUREGEN,
                        )
                        model_status = gr.Markdown(
                            value=f"**Loaded:** {model_mgr.current_model_display}  \n**Texture:** {model_mgr.current_tex_display}"
                        )
                        with gr.Row():
                            load_model_btn = gr.Button(value="Apply Model Change", variant="secondary", min_width=100)

                    with gr.Accordion('Advanced Options', open=False):
                        with gr.Row():
                            decode_mode = gr.Radio(label='Decoding Mode',
                                                   info='The resolution for exporting mesh from generated vectset',
                                                   choices=['Low', 'Standard', 'High'],
                                                   value='Standard')
                        with gr.Row():
                            check_box_rembg = gr.Checkbox(value=True, label='Remove Background', min_width=100)
                            randomize_seed = gr.Checkbox(label="Randomize seed", value=True, min_width=100)
                        seed = gr.Slider(
                            label="Seed",
                            minimum=0,
                            maximum=MAX_SEED,
                            step=1,
                            value=1234,
                            min_width=100,
                        )
                        with gr.Row():
                            num_steps = gr.Slider(maximum=100,
                                                  minimum=1,
                                                  value=model_mgr.default_steps,
                                                  step=1, label='Inference Steps')
                            octree_resolution = gr.Slider(maximum=512, minimum=16, value=256, label='Octree Resolution')
                        with gr.Row():
                            cfg_scale = gr.Number(value=5.0, label='Guidance Scale', min_width=100)
                            num_chunks = gr.Slider(maximum=5000000, minimum=1000, value=8000,
                                                   label='Number of Chunks', min_width=100)
                    with gr.Accordion("Export", open=True):
                        with gr.Row():
                            file_type = gr.Dropdown(label='File Type', choices=SUPPORTED_FORMATS,
                                                    value='glb', min_width=100)
                            reduce_face = gr.Checkbox(label='Simplify Mesh', value=False, min_width=100)
                            export_texture = gr.Checkbox(label='Include Texture', value=False,
                                                         visible=False, min_width=100)
                        target_face_num = gr.Slider(maximum=1000000, minimum=100, value=10000,
                                                    label='Target Face Number')
                        with gr.Row():
                            confirm_export = gr.Button(value="Transform", min_width=100)
                            file_export = gr.DownloadButton(label="Download", variant='primary',
                                                            interactive=False, min_width=100)

            with gr.Column(scale=6):
                with gr.Column():
                    with gr.Accordion('Generated Mesh', open=True):
                        html_gen_mesh = gr.HTML(HTML_OUTPUT_PLACEHOLDER, label='Output')
                    with gr.Accordion('Part Decomposition', open=False):
                        gr.Markdown("Segment the generated mesh into semantic parts using P3-SAM, then generate completed parts with XPart, and prepare STL files for 3D printing.")
                        with gr.Row():
                            segment_btn = gr.Button(value="1. Segment Parts", variant="primary", min_width=100)
                            generate_parts_btn = gr.Button(value="2. Generate Parts", variant="primary", min_width=100)
                            prepare_print_btn = gr.Button(value="3. Prepare for Printing", variant="primary", min_width=100)
                        part_status = gr.Markdown(value="Load a mesh first, then click **Segment**.")
                        with gr.Row():
                            part_segmented = gr.Model3D(clear_color=[0.0, 0.0, 0.0, 0.0], label="Segmented Mesh")
                            part_generated = gr.Model3D(clear_color=[0.0, 0.0, 0.0, 0.0], label="Generated Parts")
                        with gr.Row():
                            print_download = gr.File(label="Download STL Files (ZIP)", visible=True, interactive=False)
                        part_face_id = gr.File(label="Face IDs (.npy)", visible=False)
                        # Hidden state to carry mesh path from shape gen to part pipeline
                        part_mesh_state = gr.State(value=None)
                    with gr.Accordion('Exporting Mesh', open=True):
                        html_export_mesh = gr.HTML(HTML_OUTPUT_PLACEHOLDER, label='Output')
                    with gr.Accordion('Mesh Statistic', open=False):
                        stats = gr.Json({}, label='Mesh Stats')

            with gr.Column(scale=3 if model_mgr.is_mv_mode else 2):
                with gr.Column():
                    with gr.Accordion('Image to 3D Gallery', open=not model_mgr.is_mv_mode, visible=not model_mgr.is_mv_mode) as tab_gi:
                        with gr.Row():
                            gr.Examples(examples=example_is, inputs=[image],
                                        label=None, examples_per_page=18)

                    with gr.Accordion('Text to 3D Gallery', open=False, visible=HAS_T2I and not model_mgr.is_mv_mode) as tab_gt:
                        with gr.Row():
                            gr.Examples(examples=example_ts, inputs=[caption],
                                        label=None, examples_per_page=18)
                    with gr.Accordion('MultiView to 3D Gallery', open=model_mgr.is_mv_mode, visible=model_mgr.is_mv_mode) as tab_mv_gallery:
                        with gr.Row():
                            gr.Examples(examples=example_mvs,
                                        inputs=[mv_image_front, mv_image_back, mv_image_left, mv_image_right],
                                        label=None, examples_per_page=6)

        if not HAS_TEXTUREGEN:
            gr.HTML("""
            <div style="margin-top: 5px;"  align="center">
                <b>Warning: </b>
                Texture synthesis is disable due to missing requirements,
                 please install requirements following <a href="https://github.com/Tencent/Hunyuan3D-2?tab=readme-ov-file#install-requirements">README.md</a>to activate it.
            </div>
            """)
        if not args.enable_t23d:
            gr.HTML("""
            <div style="margin-top: 5px;"  align="center">
                <b>Warning: </b>
                Text to 3D is disable. To activate it, please run `python gradio_app.py --enable_t23d`.
            </div>
            """)

        btn.click(
            shape_generation,
            inputs=[
                caption,
                image,
                mv_image_front,
                mv_image_back,
                mv_image_left,
                mv_image_right,
                num_steps,
                cfg_scale,
                seed,
                octree_resolution,
                check_box_rembg,
                num_chunks,
                randomize_seed,
            ],
            outputs=[file_out, html_gen_mesh, stats, seed]
        ).then(
            lambda p: (gr.update(visible=False, value=False), gr.update(interactive=True), gr.update(interactive=True),
                     gr.update(interactive=False), p),
            inputs=[file_out],
            outputs=[export_texture, reduce_face, confirm_export, file_export, part_mesh_state],
        )

        btn_all.click(
            generation_all,
            inputs=[
                caption,
                image,
                mv_image_front,
                mv_image_back,
                mv_image_left,
                mv_image_right,
                num_steps,
                cfg_scale,
                seed,
                octree_resolution,
                check_box_rembg,
                num_chunks,
                randomize_seed,
            ],
            outputs=[file_out, file_out2, html_gen_mesh, stats, seed]
        ).then(
            lambda p: (gr.update(visible=True, value=True), gr.update(interactive=False), gr.update(interactive=True),
                     gr.update(interactive=False), p),
            inputs=[file_out],
            outputs=[export_texture, reduce_face, confirm_export, file_export, part_mesh_state],
        )

        # ------------------------------------------------------------------
        # Model selection event handlers
        # ------------------------------------------------------------------
        def on_model_family_change(family_key):
            """Update speed variant choices when model family changes."""
            variants = get_available_variants(family_key)
            return gr.update(choices=variants, value=variants[0])

        model_family.change(
            on_model_family_change,
            inputs=[model_family],
            outputs=[speed_variant],
        )

        def on_speed_variant_change(family_key, variant_key):
            """Load the selected shape model and update UI."""
            info = model_mgr.load_shape_model(family_key, variant_key)

            # Update model status text
            status_text = f"**Loaded:** {info['model_display']}  \n**Texture:** {model_mgr.current_tex_display}"

            return (
                gr.update(value=info["default_steps"]),          # num_steps slider
                gr.update(value=status_text),                    # model_status markdown
                gr.update(visible=info["is_mv"]),                # tab_mv prompt accordion
                gr.update(visible=not info["is_mv"]),            # tab_ip prompt accordion
                gr.update(visible=HAS_T2I and not info["is_mv"]), # tab_tp prompt accordion
                gr.update(visible=info["is_mv"]),                # tab_mv gallery accordion
                gr.update(visible=not info["is_mv"]),            # tab_gi gallery accordion
                gr.update(visible=HAS_T2I and not info["is_mv"]),# tab_gt gallery accordion
            )

        speed_variant.change(
            on_speed_variant_change,
            inputs=[model_family, speed_variant],
            outputs=[
                num_steps, model_status,
                tab_mv, tab_ip, tab_tp,          # prompt accordions
                tab_mv_gallery, tab_gi, tab_gt,   # gallery accordions
            ],
        )

        def on_tex_model_change(tex_key):
            """Load the selected texture model."""
            model_mgr.load_tex_model(tex_key)
            status_text = f"**Loaded:** {model_mgr.current_model_display}  \n**Texture:** {model_mgr.current_tex_display}"
            return gr.update(value=status_text)

        tex_model.change(
            on_tex_model_change,
            inputs=[tex_model],
            outputs=[model_status],
        )

        def on_decode_mode_change(value):
            if value == 'Low':
                return gr.update(value=196)
            elif value == 'Standard':
                return gr.update(value=256)
            else:
                return gr.update(value=384)

        decode_mode.change(on_decode_mode_change, inputs=[decode_mode], outputs=[octree_resolution])

        # ------------------------------------------------------------------
        # Part Decomposition (P3-SAM + XPart) event handlers
        # ------------------------------------------------------------------
        _PARTSEG_AVAILABLE = False
        try:
            from hy3dgen.partseg import PartSegManager
            _partseg_mgr = PartSegManager()
            _PARTSEG_AVAILABLE = True
        except Exception as e:
            print(f"Part segmentation unavailable: {e}")

        def on_segment_parts(mesh_path, seed):
            """Run P3-SAM segmentation on the generated mesh — with live progress."""
            import gc, time
            import numpy as np
            import pickle as _pickle
            import logging
            _mem_logger = logging.getLogger("gradio.memory")

            if mesh_path is None:
                raise gr.Error("Please generate a mesh first (click Gen Shape or Gen Textured Shape).")
            if not _PARTSEG_AVAILABLE:
                raise gr.Error("Part segmentation is not available. Check dependencies (spconv, torch_scatter, etc.).")

            # ---- Phase 1: GPU Cleanup (yield status) ----
            gpu_total = torch.cuda.get_device_properties(0).total_memory / 1e6 if torch.cuda.is_available() else 0
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
            yield None, None, None, (
                f"**🧹 Phase 1/5: Freeing GPU memory**\n\n"
                f"**Device:** {gpu_name} ({gpu_total:.0f} MB)\n"
                f"Moving shape model to CPU..."
            )

            if model_mgr.shape_pipeline is not None:
                model_mgr.shape_pipeline.to('cpu')
            if hasattr(model_mgr, 'tex_pipeline') and model_mgr.tex_pipeline is not None:
                try: model_mgr.tex_pipeline.to('cpu')
                except Exception: pass

            for _ in range(3):
                gc.collect()
                torch.cuda.empty_cache()

            free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else -1
            yield None, None, None, (
                f"**🧹 Phase 1/5: GPU Cleanup — done**\n\n"
                f"**Free VRAM:** {free_mb:.0f} / {gpu_total:.0f} MB\n"
                f"Loading mesh..."
            )

            # ---- Phase 2: Load Mesh ----
            mesh = trimesh.load(mesh_path, force='mesh', process=False)
            nv, nf = len(mesh.vertices), len(mesh.faces)
            est_time = "2-4 min" if nf < 50000 else "4-6 min"

            yield None, None, None, (
                f"**📂 Phase 2/5: Mesh Loaded**\n\n"
                f"**Vertices:** {nv:,}  |  **Faces:** {nf:,}\n"
                f"**Estimated time:** {est_time} (GPU inference)\n\n"
                f"**🚀 Phase 3/5: P3-SAM Segmentation (GPU)...**\n"
                f"• Sampling 100K surface points\n"
                f"• Extracting Sonata 3D features\n"
                f"• 400 prompt points × FPS sampling\n"
                f"• ~50 batches of GPU inference\n"
                f"• NMS clustering + label fixing\n"
                f"⏳ Running — please wait..."
            )

            # ---- Phase 3: Run P3-SAM ----
            t0 = time.time()
            try:
                aabb, face_ids = _partseg_mgr.segment(mesh, seed=seed)
            except Exception as seg_exc:
                gc.collect(); torch.cuda.empty_cache()
                raise gr.Error(f"Segmentation failed (likely out of GPU memory): {seg_exc}")

            elapsed = time.time() - t0
            unique_ids = np.unique(face_ids)
            n_parts = len(unique_ids) - (1 if -1 in unique_ids else 0)

            free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else -1
            yield None, None, None, (
                f"**✅ Phase 3/5: Segmentation Complete**\n\n"
                f"**Parts found:** {n_parts}\n"
                f"**Time:** {elapsed:.0f}s (~{elapsed/60:.1f} min)\n"
                f"**Free VRAM:** {free_mb:.0f} / {gpu_total:.0f} MB\n\n"
                f"**🎨 Phase 4/5: Unloading P3-SAM from GPU, coloring mesh...**"
            )

            # ---- Phase 4: Unload P3-SAM + Color ----
            try:
                _partseg_mgr.unload_automask()
            except Exception as unload_exc:
                _mem_logger.warning("Failed to unload P3-SAM: %s", unload_exc)

            # Restore shape pipeline only if enough VRAM
            if model_mgr.shape_pipeline is not None:
                free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else 99999
                if free_mb > 4000:
                    model_mgr.shape_pipeline.to('cuda')
            gc.collect(); torch.cuda.empty_cache()

            # Color mesh by part ID
            color_map = {}
            for i in unique_ids:
                if i == -1: continue
                color_map[i] = np.random.RandomState(int(i)).randint(0, 255, 3)
            face_colors = np.array(
                [color_map.get(i, [0, 0, 0]) for i in face_ids]
            ).astype(np.uint8)
            mesh_save = mesh.copy()
            mesh_save.visual.face_colors = face_colors

            yield None, None, None, (
                f"**🎨 Phase 4/5: Mesh Colored**\n\n"
                f"**{n_parts} parts** found & colored\n"
                f"**💾 Phase 5/5: Saving results...**"
            )

            # ---- Phase 5: Save ----
            save_folder = gen_save_folder()
            segmented_path = os.path.join(save_folder, 'segmented.glb')
            mesh_save.export(segmented_path)
            face_id_path = os.path.join(save_folder, 'face_ids.npy')
            np.save(face_id_path, face_ids)

            aabb_pkl_path = os.path.join(save_folder, 'aabb.pkl')
            with open(aabb_pkl_path, 'wb') as f:
                _pickle.dump({'aabb': aabb, 'mesh_path': mesh_path}, f)

            part_state = {'aabb_pkl': aabb_pkl_path, 'mesh_path': mesh_path}
            del mesh, mesh_save, face_colors
            gc.collect()

            yield segmented_path, face_id_path, part_state, (
                f"**✅ Done!** Found **{n_parts} parts** in {elapsed:.0f}s.\n\n"
                f"Click **'2. Generate Parts'** to create printable part meshes."
            )

        def on_generate_parts(part_state, seed):
            """Run XPart to generate completed parts — with live progress."""
            import pickle as _pickle, gc, time, logging
            _mem_logger = logging.getLogger("gradio.memory")

            if part_state is None or not isinstance(part_state, dict) or 'aabb_pkl' not in part_state:
                raise gr.Error("Please run 'Segment Parts' first.")
            if not os.path.exists(part_state['aabb_pkl']):
                raise gr.Error("Segmentation data no longer available. Please run 'Segment Parts' again.")

            with open(part_state['aabb_pkl'], 'rb') as f:
                saved = _pickle.load(f)
            aabb = saved['aabb']
            mesh_path = saved['mesh_path']

            gpu_total = torch.cuda.get_device_properties(0).total_memory / 1e6 if torch.cuda.is_available() else 0
            n_parts = len(aabb) if aabb is not None else 0

            # ---- Phase 1: GPU Cleanup ----
            yield None, None, part_state, (
                f"**🧹 Phase 1/4: Freeing GPU memory**\n\n"
                f"Moving models to CPU...\n"
                f"Parts to generate: **{n_parts}**"
            )

            if model_mgr.shape_pipeline is not None:
                model_mgr.shape_pipeline.to('cpu')
            try: _partseg_mgr.unload_automask()
            except Exception: pass

            gc.collect(); torch.cuda.empty_cache()
            gc.collect(); torch.cuda.empty_cache()

            free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else -1
            est_min = max(1, n_parts * 0.5)
            yield None, None, part_state, (
                f"**🧹 Phase 1/4: GPU Cleanup — done**\n\n"
                f"**Free VRAM:** {free_mb:.0f} / {gpu_total:.0f} MB\n"
                f"**Parts:** {n_parts}\n\n"
                f"**🚀 Phase 2/4: Loading XPart model (GPU)...**\n"
                f"Downloading from HuggingFace if needed..."
            )

            # ---- Phase 2: Load XPart + Run ----
            t0 = time.time()
            yield None, None, part_state, (
                f"**🚀 Phase 2/4: XPart Generation (GPU)...**\n\n"
                f"**Parts:** {n_parts}\n"
                f"**Estimated time:** {est_min:.0f}-{est_min*1.5:.0f} min\n"
                f"• Per-part latent diffusion (50 steps each)\n"
                f"• Marching cubes surface extraction\n"
                f"⏳ Running — please wait..."
            )

            try:
                obj_mesh, bbox_mesh, explode_mesh = _partseg_mgr.generate_parts(
                    mesh_path, aabb, seed=seed
                )
            except Exception as xp_exc:
                gc.collect(); torch.cuda.empty_cache()
                raise gr.Error(f"Part generation failed (likely out of GPU memory): {xp_exc}")

            elapsed = time.time() - t0
            free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else -1
            yield None, None, part_state, (
                f"**✅ Phase 2/4: Generation Complete**\n\n"
                f"**Time:** {elapsed:.0f}s (~{elapsed/60:.1f} min)\n"
                f"**Free VRAM:** {free_mb:.0f} / {gpu_total:.0f} MB\n\n"
                f"**🧹 Phase 3/4: Unloading XPart from GPU...**"
            )

            # ---- Phase 3: Unload XPart ----
            try:
                _partseg_mgr.unload_pipeline()
            except Exception as unload_exc:
                _mem_logger.warning("Failed to unload XPart: %s", unload_exc)

            if model_mgr.shape_pipeline is not None:
                free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else 99999
                if free_mb > 4000:
                    model_mgr.shape_pipeline.to('cuda')
            gc.collect(); torch.cuda.empty_cache()

            # ---- Phase 4: Save ----
            save_folder = gen_save_folder()
            parts_path = os.path.join(save_folder, 'parts.glb')
            explode_path = os.path.join(save_folder, 'exploded.glb')
            obj_mesh.export(parts_path)
            explode_mesh.export(explode_path)

            # Store parts path in state for downstream slicer
            part_state['parts_path'] = parts_path
            part_state['explode_path'] = explode_path

            free_mb = torch.cuda.mem_get_info()[0] / 1e6 if torch.cuda.is_available() else -1
            yield parts_path, explode_path, part_state, (
                f"**✅ Done!** Parts generated in {elapsed:.0f}s.\n\n"
                f"**Free VRAM:** {free_mb:.0f} / {gpu_total:.0f} MB\n\n"
                f"The exploded view shows all parts separated.\n\n"
                f"Click **'3. Prepare for Printing'** to generate STL files."
            )

        segment_btn.click(
            on_segment_parts,
            inputs=[part_mesh_state, seed],
            outputs=[part_segmented, part_face_id, part_mesh_state, part_status],
        )
        generate_parts_btn.click(
            on_generate_parts,
            inputs=[part_mesh_state, seed],
            outputs=[part_generated, part_segmented, part_mesh_state, part_status],
        )

        def on_prepare_print(part_state, seed):
            """Run slicer on generated parts — with live progress."""
            import gc, time, zipfile, logging
            _mem_logger = logging.getLogger("gradio.memory")

            if part_state is None or not isinstance(part_state, dict) or 'parts_path' not in part_state:
                raise gr.Error("Please run 'Segment Parts' and 'Generate Parts' first.")
            parts_path = part_state['parts_path']
            if not os.path.exists(parts_path):
                raise gr.Error("Parts mesh no longer available. Please run 'Generate Parts' again.")

            gpu_total = torch.cuda.get_device_properties(0).total_memory / 1e6 if torch.cuda.is_available() else 0

            # ---- Phase 1: Load parts ----
            yield None, None, (
                f"**📂 Phase 1/4: Loading parts mesh...**\n\n"
                f"Loading: `{os.path.basename(parts_path)}`"
            )

            parts_mesh = trimesh.load(parts_path, force='mesh')

            # Handle both Trimesh and Scene
            if isinstance(parts_mesh, trimesh.Trimesh):
                scene = trimesh.Scene()
                scene.add_geometry(parts_mesh, geom_name='generated_parts')
            elif isinstance(parts_mesh, trimesh.Scene):
                scene = parts_mesh
            else:
                raise gr.Error(f"Unexpected mesh type: {type(parts_mesh)}")

            n_geoms = len(scene.geometry)
            yield None, None, (
                f"**📂 Phase 1/4: Parts loaded**\n\n"
                f"**Geometries:** {n_geoms}\n\n"
                f"**🔧 Phase 2/4: Running slicer...**\n"
                f"• Checking bed fit\n"
                f"• Generating pin/hole connectors\n"
                f"• Exporting STL files\n"
                f"⏳ Please wait..."
            )

            # ---- Phase 2: Run slicer ----
            t0 = time.time()
            try:
                from hy3dgen.slicer import SlicerManager
                from hy3dgen.slicer.config import load_profile

                slicer = SlicerManager()
                save_folder = gen_save_folder()
                stl_dir = os.path.join(save_folder, 'stl')
                os.makedirs(stl_dir, exist_ok=True)

                result = slicer.process(
                    scene,
                    output_dir=stl_dir,
                    skip_connectors=False,
                )
            except Exception as sl_exc:
                gc.collect()
                raise gr.Error(f"Slicer failed: {sl_exc}")

            elapsed = time.time() - t0
            n_parts = len(result)
            fitted = sum(1 for p in result if p.fits_bed)
            oversized = n_parts - fitted

            yield None, None, (
                f"**✅ Phase 2/4: Slicing complete**\n\n"
                f"**Parts:** {n_parts}  |  "
                f"**Fit bed:** {fitted}/{n_parts}  |  "
                f"**Time:** {elapsed:.0f}s\n"
                f"{'⚠ ' + str(oversized) + ' part(s) exceed bed size' if oversized else '✅ All parts fit the bed'}\n\n"
                f"**📦 Phase 3/4: Creating ZIP archive...**"
            )

            # ---- Phase 3: Create ZIP ----
            zip_path = os.path.join(save_folder, 'print_parts.zip')
            stl_count = 0
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for fname in sorted(os.listdir(stl_dir)):
                    if fname.endswith('.stl') or fname.endswith('.txt'):
                        zf.write(os.path.join(stl_dir, fname), fname)
                        if fname.endswith('.stl'):
                            stl_count += 1

            zip_size_mb = os.path.getsize(zip_path) / (1024 * 1024)

            yield zip_path, gr.update(), (
                f"**📦 Phase 3/4: Archive ready**\n\n"
                f"**STL files:** {stl_count}  |  "
                f"**ZIP size:** {zip_size_mb:.1f} MB\n\n"
                f"**💾 Phase 4/4: Done!**"
            )

            # ---- Phase 4: Done ----
            del parts_mesh, scene
            gc.collect()

            yield gr.update(value=zip_path), gr.update(), (
                f"**✅ Done!** Print parts ready.\n\n"
                f"**STL files:** {stl_count}  |  "
                f"**Fit bed:** {fitted}/{n_parts}  |  "
                f"**Time:** {elapsed:.0f}s\n\n"
                f"⬇️ **Download the ZIP file** below and extract to get individual STL files.\n"
                f"📋 A README.txt with assembly notes is included in the archive."
            )

        prepare_print_btn.click(
            on_prepare_print,
            inputs=[part_mesh_state, seed],
            outputs=[print_download, part_generated, part_status],
        )

        def on_export_click(file_out, file_out2, file_type, reduce_face, export_texture, target_face_num):
            if file_out is None:
                raise gr.Error('Please generate a mesh first.')

            print(f'exporting {file_out}')
            print(f'reduce face to {target_face_num}')
            if export_texture:
                mesh = trimesh.load(file_out2)
                save_folder = gen_save_folder()
                path = export_mesh(mesh, save_folder, textured=True, type=file_type)

                # for preview
                save_folder = gen_save_folder()
                _ = export_mesh(mesh, save_folder, textured=True)
                model_viewer_html = build_model_viewer_html(save_folder, height=HTML_HEIGHT, width=HTML_WIDTH,
                                                            textured=True)
            else:
                mesh = trimesh.load(file_out)
                mesh = model_mgr.floater_remover(mesh)
                mesh = model_mgr.degenerate_face_remover(mesh)
                if reduce_face:
                    mesh = model_mgr.face_reducer(mesh, target_face_num)
                save_folder = gen_save_folder()
                path = export_mesh(mesh, save_folder, textured=False, type=file_type)

                # for preview
                save_folder = gen_save_folder()
                _ = export_mesh(mesh, save_folder, textured=False)
                model_viewer_html = build_model_viewer_html(save_folder, height=HTML_HEIGHT, width=HTML_WIDTH,
                                                            textured=False)
            print(f'export to {path}')
            return model_viewer_html, gr.update(value=path, interactive=True)

        confirm_export.click(
            on_export_click,
            inputs=[file_out, file_out2, file_type, reduce_face, export_texture, target_face_num],
            outputs=[html_export_mesh, file_export]
        )

    return demo


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, default='tencent/Hunyuan3D-2mini')
    parser.add_argument("--subfolder", type=str, default='hunyuan3d-dit-v2-mini-turbo')
    parser.add_argument("--texgen_model_path", type=str, default='tencent/Hunyuan3D-2')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--host', type=str, default='0.0.0.0')
    parser.add_argument('--device', type=str, default='cuda')
    parser.add_argument('--mc_algo', type=str, default='mc')
    parser.add_argument('--cache-path', type=str, default='gradio_cache')
    parser.add_argument('--enable_t23d', action='store_true')
    parser.add_argument('--disable_tex', action='store_true')
    parser.add_argument('--enable_flashvdm', action='store_true')
    parser.add_argument('--compile', action='store_true')
    parser.add_argument('--low_vram_mode', action='store_true')
    args = parser.parse_args()

    SAVE_DIR = args.cache_path
    os.makedirs(SAVE_DIR, exist_ok=True)

    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

    # ------------------------------------------------------------------
    # Initialize ModelManager (replaces old MV_MODE, TURBO_MODE, workers)
    # ------------------------------------------------------------------
    model_mgr = ModelManager(
        device=args.device,
        cli_model_path=args.model_path,
        cli_subfolder=args.subfolder,
        cli_texgen_path=args.texgen_model_path,
        enable_flashvdm_flag=args.enable_flashvdm,
        mc_algo=args.mc_algo,
        low_vram_mode=args.low_vram_mode,
    )

    HTML_HEIGHT = 690 if model_mgr.is_mv_mode else 650
    HTML_WIDTH = 500
    HTML_OUTPUT_PLACEHOLDER = f"""
    <div style='height: {650}px; width: 100%; border-radius: 8px; border-color: #e5e7eb; border-style: solid; border-width: 1px; display: flex; justify-content: center; align-items: center;'>
      <div style='text-align: center; font-size: 16px; color: #6b7280;'>
        <p style="color: #8d8d8d;">Welcome to Hunyuan3D!</p>
        <p style="color: #8d8d8d;">No mesh here.</p>
      </div>
    </div>
    """

    INPUT_MESH_HTML = """
    <div style='height: 490px; width: 100%; border-radius: 8px; 
    border-color: #e5e7eb; order-style: solid; border-width: 1px;'>
    </div>
    """
    example_is = get_example_img_list()
    example_ts = get_example_txt_list()
    example_mvs = get_example_mv_list()

    SUPPORTED_FORMATS = ['glb', 'obj', 'ply', 'stl']

    from hy3dgen.shapegen import FaceReducer, FloaterRemover, DegenerateFaceRemover, MeshSimplifier
    from hy3dgen.shapegen.pipelines import export_to_trimesh
    from hy3dgen.rembg import BackgroundRemover

    # Load shape model via ModelManager
    model_mgr.load_shape_model(model_mgr.shape_family, model_mgr.shape_variant)
    if args.compile:
        model_mgr.shape_pipeline.compile()

    # Init post-process workers (stateless, no GPU VRAM concern)
    model_mgr.floater_remover = FloaterRemover()
    model_mgr.degenerate_face_remover = DegenerateFaceRemover()
    model_mgr.face_reducer = FaceReducer()
    model_mgr.rmbg_worker = BackgroundRemover()

    # Texture generation (optional)
    HAS_TEXTUREGEN = False
    if not args.disable_tex:
        try:
            model_mgr.load_tex_model(model_mgr.tex_key)
            HAS_TEXTUREGEN = model_mgr.has_texgen
        except Exception as e:
            print(e)
            print("Failed to load texture generator.")
            print('Please try to install requirements by following README.md')
            HAS_TEXTUREGEN = False

    # Text-to-image (optional)
    HAS_T2I = True
    if args.enable_t23d:
        from hy3dgen.text2image import HunyuanDiTPipeline
        model_mgr.t2i_worker = HunyuanDiTPipeline(
            'Tencent-Hunyuan/HunyuanDiT-v1.1-Diffusers-Distilled', device=args.device
        )
        HAS_T2I = True

    # https://discuss.huggingface.co/t/how-to-serve-an-html-file/33921/2
    # create a FastAPI app
    app = FastAPI()
    # create a static directory to store the static files
    static_dir = Path(SAVE_DIR).absolute()
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir, html=True), name="static")
    shutil.copytree('./assets/env_maps', os.path.join(static_dir, 'env_maps'), dirs_exist_ok=True)

    if model_mgr.low_vram_mode:
        torch.cuda.empty_cache()
    demo = build_app()
    app = gr.mount_gradio_app(app, demo, path="/")
    uvicorn.run(app, host=args.host, port=args.port, workers=1)
