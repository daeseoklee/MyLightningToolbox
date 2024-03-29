from math import sin, pi
from urllib.parse import non_hierarchical
from typing import Union, List
import torch
from torch.optim.lr_scheduler import _LRScheduler
import pytorch_lightning as pl
from torch.utils.data import DataLoader
import torch.nn as nn
from math import ceil, floor

def get_scheduler(optimizer:torch.optim.Optimizer,
                  sched:str, **kwargs):
    if sched == 'lin':
        return WarmupLinearDecay(optimizer, **kwargs)
    elif sched == 'cos':
        return WarmupCosineDecay(optimizer, **kwargs)
    elif sched == 'con':
        return WarmupConstant(optimizer, **kwargs)
    else:
        raise Exception()
    
class SchedulerLateTotalstepsSetter(pl.Callback):
    def __init__(self, length_from='sampler'):
        self.length_from = length_from
    def get_batch_per_epoch(self, loader:DataLoader):
        if self.length_from == 'sampler':
            assert loader.sampler is not None
            assert loader.batch_size is not None
            sampler = loader.sampler
            batch_size = loader.batch_size
            assert hasattr(sampler, 'num_samples')
            num_samples = sampler.num_samples
            if num_samples is None:
                num_samples = len(sampler)
            if loader.drop_last:
                return floor(num_samples / batch_size)
            return ceil(num_samples / batch_size)
        elif self.length_from == 'dataloader':
            return len(loader)
            
            
    def on_train_start(self, trainer, pl_module:"pl.LightningModule"):
        for lr_scheduler_config in trainer.lr_scheduler_configs:
            if hasattr(lr_scheduler_config.scheduler, 'set_total_steps'):
                scheduler:LateTotalstepsScheduler = lr_scheduler_config.scheduler
                
                loader = pl_module.train_dataloader()
                batch_per_epoch_per_device = self.get_batch_per_epoch(loader)

                accumulate = trainer.accumulate_grad_batches
                max_epochs = trainer.max_epochs
                    
                total_steps = batch_per_epoch_per_device // accumulate * max_epochs
                
                scheduler.set_total_steps(total_steps, max_epochs=max_epochs)
                
        
    
class LateTotalstepsScheduler(_LRScheduler):
    def __init__(self, optimizer, last_step):
        super().__init__(optimizer, last_step)
        self.total_steps = None 
    def set_total_steps(self, total_steps, max_epochs=None):
        self.total_steps = total_steps 
        self.max_epochs = max_epochs
        if self.constant_from_epoch is not None:
            assert self.max_epochs is not None 
            self.constant_from_step = int(self.total_steps * self.constant_from_epoch / self.max_epochs)
            assert self.warmup_steps <= self.constant_from_step
        else:
            self.constant_from_step = None
            


class WarmupDecay(LateTotalstepsScheduler):
    """
    """
    
    def __init__(self, 
                 optimizer : torch.optim.Optimizer,
                 max_lr : float = 1e-4,
                 warmup_steps : int = 10000,
                 min_lr : float = 1e-10,
                 last_step : int = -1,
                 freeze_til : Union[None, List[Union[None, int]]] = None,
                 constant_from_epoch = None,
                 constant_lr = None
        ):
        
        self.min_lr = min_lr
        self.max_lr = max_lr
        self.gap_lr = max_lr - min_lr
        self.warmup_steps = warmup_steps
        self.current_step = last_step + 1
        self.constant_from_epoch = constant_from_epoch 
        self.constant_lr = constant_lr
        
        if freeze_til is not None:
            assert type(freeze_til) == list
            assert len(optimizer.param_groups) == len(freeze_til)
            self.freeze_til = freeze_til 
        
        super().__init__(optimizer, last_step)
        
        self.init_lr()
    
    def init_lr(self):
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self.min_lr

    def get_lr(self):
        if self.current_step <= self.warmup_steps:
            return self.min_lr + self.gap_lr * self.current_step / self.warmup_steps
        elif self.constant_from_epoch is not None and self.current_step >= self.constant_from_step:
            if self.constant_lr is not None:
                return self.constant_lr
            return self.last_lr 
        else:
            return self.get_lr_after_warmup()
    
    def get_lr_after_warmup(self):
        raise Exception('Should be implemented in the subclass')
    

    def step(self):
        self.current_step += 1
        lr = self.get_lr()
        self.last_lr = lr 
        for i, param_group in enumerate(self.optimizer.param_groups):
            if hasattr(self, 'freeze_til') and self.freeze_til[i] is not None:
                if self.freeze_til[i] == -1 or self.current_step <= self.freeze_til[i]:
                    param_group['lr'] = 0.0
                else:
                    param_group['lr'] = lr
            else:
                param_group['lr'] = lr


class WarmupLinearDecay(WarmupDecay):
    def get_lr_after_warmup(self):
        if self.current_step < self.total_steps:
            steps_from_apex = self.current_step - self.warmup_steps
            return self.max_lr - self.gap_lr * steps_from_apex / (self.total_steps - self.warmup_steps)

        return self.min_lr
    
class WarmupCosineDecay(WarmupDecay):
    def get_lr_after_warmup(self):
        if self.current_step < self.total_steps:
            steps_from_apex = self.current_step - self.warmup_steps
            phase = steps_from_apex / (self.total_steps - self.warmup_steps)
            return self.max_lr - self.gap_lr * (0.5 + 0.5 * sin(pi * (phase - 0.5)))
            
        return self.min_lr
    
class WarmupConstant(WarmupDecay):
    def get_lr_after_warmup(self):
        return self.max_lr


""" 
class WarmupLinearDecay(LateTotalstepsScheduler):
    
    def __init__(self, 
                 optimizer : torch.optim.Optimizer,
                 max_lr : float = 1e-4,
                 warmup_steps : int = 10000,
                 min_lr : float = 1e-10,
                 last_step : int = -1 
        ):
        
        self.min_lr = min_lr
        self.max_lr = max_lr
        self.gap_lr = max_lr - min_lr
        self.warmup_steps = warmup_steps
        self.current_step = last_step + 1
        
        super().__init__(optimizer, last_step)
        
        self.init_lr()
    
    def init_lr(self):
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self.min_lr

    def get_lr(self):
        if self.current_step <= self.warmup_steps:
            return self.min_lr + self.gap_lr * self.current_step / self.warmup_steps
        
        elif self.current_step < self.total_steps:
            steps_from_apex = self.current_step - self.warmup_steps
            return self.max_lr - self.gap_lr * steps_from_apex / (self.total_steps - self.warmup_steps)
        else:
            return self.min_lr

    def step(self):
        self.current_step += 1
        lr = self.get_lr()
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr
            
class WarmupCosineDecay(LateTotalstepsScheduler):

    def __init__(self, 
                 optimizer : torch.optim.Optimizer,
                 max_lr : float = 1e-4,
                 warmup_steps : int = 10000,
                 min_lr : float = 1e-10,
                 last_step : int = -1 
        ):

        self.min_lr = min_lr
        self.max_lr = max_lr
        self.gap_lr = max_lr - min_lr
        self.warmup_steps = warmup_steps
        self.current_step = last_step + 1
        
        super().__init__(optimizer, last_step)
        
        self.init_lr()
    
    def init_lr(self):
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self.min_lr

    def get_lr(self):
        if self.current_step <= self.warmup_steps:
            return self.min_lr + self.gap_lr * self.current_step / self.warmup_steps
        
        elif self.current_step < self.total_steps:
            steps_from_apex = self.current_step - self.warmup_steps
            phase = steps_from_apex / (self.total_steps - self.warmup_steps)
            return self.max_lr - self.gap_lr * (0.5 + 0.5 * sin(pi * (phase - 0.5)))
        else:
            return self.min_lr

    def step(self):
        self.current_step += 1
        lr = self.get_lr()
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr
    
class WarmupConstant(LateTotalstepsScheduler):
    
    def __init__(self, 
                 optimizer : torch.optim.Optimizer,
                 max_lr : float = 1e-4,
                 warmup_steps : int = 10000,
                 min_lr : float = 1e-10,
                 last_step : int = -1 
        ):
        
        self.min_lr = min_lr
        self.max_lr = max_lr
        self.gap_lr = max_lr - min_lr
        self.warmup_steps = warmup_steps
        self.current_step = last_step + 1
        
        super().__init__(optimizer, last_step)
        
        self.init_lr()
    
    def init_lr(self):
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = self.min_lr

    def get_lr(self):
        if self.current_step <= self.warmup_steps:
            return self.min_lr + self.gap_lr * self.current_step / self.warmup_steps
        else:
            return self.max_lr

    def step(self):
        self.current_step += 1
        lr = self.get_lr()
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr


"""


