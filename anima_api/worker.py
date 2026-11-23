import gc,hashlib,json,os,time,traceback
from . import store
from .settings import ROOT,OUTPUT,MODEL,REVISION

def main():
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(ROOT/'.cache/huggingface'))
    import torch,psutil
    from diffusers import ModularPipeline
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    try:
        path=(ROOT/'.state/model-path.txt').read_text().strip()
        pipeline=ModularPipeline.from_pretrained(path,local_files_only=True,trust_remote_code=False)
        pipeline.load_components(pretrained_model_name_or_path=path,local_files_only=True,revision=None,dtype=torch.bfloat16)
        pipeline.to('cpu')
        if hasattr(pipeline.vae,'enable_tiling'):pipeline.vae.enable_tiling()
        store.status('model',{'state':'READY','model':MODEL,'revision':REVISION,'device':'cpu','dtype':'bfloat16','ready_at':time.time()})
        print('MODEL_READY',flush=True)
    except Exception as e:
        traceback.print_exc();store.status('model',{'state':'ERROR','error':str(e)[:1000]});return
    while True:
        task=store.claim()
        if not task:time.sleep(.25);continue
        request=json.loads(task['request']);started=time.monotonic()
        try:
            generator=torch.Generator(device='cpu').manual_seed(request['seed'])
            with torch.inference_mode():
                state=pipeline(prompt=request['prompt'],negative_prompt=request['negative_prompt'],height=request['height'],width=request['width'],
                    num_inference_steps=request['steps'],max_sequence_length=128,generator=generator)
            image=state.images[0];target=OUTPUT/(task['id']+'.png');temp=target.with_suffix('.partial')
            image.save(temp,format='PNG');temp.replace(target)
            metadata={'model':MODEL,'revision':REVISION,'device':'cpu','dtype':'bfloat16','elapsed_seconds':time.monotonic()-started,
                'rss_at_completion_bytes':psutil.Process().memory_info().rss,'width':image.width,'height':image.height,'steps':request['steps'],
                'seed':request['seed'],'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            store.finish(task['id'],metadata=metadata);print('GENERATED',task['id'],metadata,flush=True)
            del state,image;gc.collect()
        except Exception as e:traceback.print_exc();store.finish(task['id'],error=str(e)[:2000])
if __name__=='__main__':main()
