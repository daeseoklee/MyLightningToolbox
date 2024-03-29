from pathlib import Path
from typing import Dict, Optional
import psutil
import os
import json
import csv
import pytorch_lightning as pl
from pytorch_lightning.loggers import TensorBoardLogger 

def quote_args(arg_list):
    def has_to_quote(arg):
        if not arg.startswith('-') and '-' in arg:
            return True
        return any(c in arg for c in ['(', ')', ':', ','])

    return [f'"{arg}"' if has_to_quote(arg) else arg for arg in arg_list]

class MyLogger(TensorBoardLogger):
    def __init__(self, metrics_to_log=['val_loss'], train_info=['dataset_config', 'train_config'], model_info=['model_config'], srcfile_prefix='', python_run_module=False, **kwargs):
        super().__init__(**kwargs)
        self.mylogger_metrics_to_log = metrics_to_log
        self.train_dir = Path(self.log_dir)
        if self.sub_dir is None:
            self.model_dir = self.train_dir 
        else:
            self.model_dir = self.train_dir.parent             
        self.train_info = train_info
        self.model_info = model_info
        self.srcfile_prefix = srcfile_prefix
        self.python_run_module = python_run_module
        self.mylogger_metrics = {}                                                         
    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None) -> None:
        for metric, val in metrics.items():
            if not metric in self.mylogger_metrics_to_log:
                continue
            self.mylogger_metrics[metric] = val
        return super().log_metrics(metrics, step=step)
    
    def create_csv_log_file(self):
        key_list = ['epoch'] + self.mylogger_metrics_to_log
        log_file = self.train_dir / 'metrics.csv'
        if log_file.exists():
            return
        with open(log_file, 'w') as f:
            writer = csv.writer(f)
            writer.writerow(key_list)
    
    def update_csv_log_file(self, trainer: "pl.Trainer", pl_module:'pl.LightningModule'):
        if trainer.sanity_checking: 
            self.mylogger_metrics = {}
            return
        
        if self.mylogger_metrics == {}:
            return

        log_file = self.train_dir / 'metrics.csv'
        new_line = [pl_module.current_epoch] + [self.mylogger_metrics[metric] for metric in self.mylogger_metrics_to_log]
        
        with open(log_file, 'a') as f:
            writer = csv.writer(f)
            writer.writerow(new_line)
        
        
    def write_command(self):
        xs = psutil.Process(os.getpid()).cmdline()
        if self.python_run_module:
            i = -1
            python_found = False
            for i in range(len(xs)):
                if xs[i].split('/')[-1].startswith('python'):
                    python_found = True 
                    break 
            assert python_found, xs
            assert xs[i+1] == '-m'
            module_name = xs[i+2]
            arg_str = ' '.join(quote_args(xs[i+3:]))
            command = f'python -m {module_name} {arg_str}'
        else:
            commandname = xs[0].split('/')[-1]
            srcfilename = xs[1].split('/')[-1] 
            assert commandname.startswith('python')
            assert srcfilename.endswith('.py')
            arg_str = ' '.join(quote_args(xs[2:]))
            command = f'{commandname} {self.srcfile_prefix}{srcfilename} ' + arg_str
        
        self.train_dir.mkdir(exist_ok=True, parents=True)
        filename = str(self.train_dir / 'command.txt')
        with open(filename, 'w') as writer:
            writer.write(command)
            
    def write_info_files(self, pl_module:'pl.LightningModule'):
        for info in self.train_info:
            assert hasattr(pl_module, info)
            filename = str(self.train_dir / f'{info}.json')
            obj = getattr(pl_module, info)
            with open(filename, 'w') as writer:
                json.dump(obj, writer)
        for info in self.model_info:
            assert hasattr(pl_module, info)
            filename = str(self.model_dir / f'{info}.json')
            obj = getattr(pl_module, info)
            with open(filename, 'w') as writer:
                json.dump(obj, writer)

class MyLoggerCallback(pl.Callback):
    def __init__(self, logger:MyLogger):
        super().__init__()
        self.logger = logger
    def on_train_start(self, trainer: "pl.Trainer", pl_module: "pl.LightningModule") -> None:
        self.logger.write_command()
        self.logger.write_info_files(pl_module)
        self.logger.create_csv_log_file()
        return super().on_train_start(trainer, pl_module)
    def on_validation_end(self, trainer: "pl.Trainer", pl_module: "pl.LightningModule") -> None:
        self.logger.update_csv_log_file(trainer, pl_module)
        return super().on_validation_end(trainer, pl_module)
