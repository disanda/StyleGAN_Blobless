# Copyright 2019 Stanislav Pidhorskyi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import os
from torch import nn
import torch
import utils


def get_model_dict(x):
    if x is None:
        return None
    if isinstance(x, nn.DataParallel):
        return x.module.state_dict()
    else:
        return x.state_dict()


def load_model(x, state_dict):
    if isinstance(x, nn.DataParallel):
        x.module.load_state_dict(state_dict)
    else:
        x.load_state_dict(state_dict)


class Checkpointer(object):
    def __init__(self, cfg, models, optimizer=None, scheduler=None, logger=None, save=True):
        self.models = models
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.cfg = cfg
        self.logger = logger
        self._save = save

    def save(self, _name, **kwargs):
        if not self._save:
            return
        data = dict()
        data["models"] = dict()
        data["optimizers"] = dict()
        for name, model in self.models.items():
            data["models"][name] = get_model_dict(model)

        if self.optimizer is not None:
            for name, optimizer in self.optimizer.items():
                data["optimizers"][name] = optimizer.state_dict()
        if self.scheduler is not None:
            data["scheduler"] = self.scheduler.state_dict()
        data.update(kwargs)

        @utils.async_func
        def save_data():
            save_file = os.path.join(self.cfg.OUTPUT_DIR, "%s.pth" % _name)
            self.logger.info("Saving checkpoint to %s" % save_file)
            torch.save(data, save_file)
            self.tag_last_checkpoint(save_file)

        save_data()

    def load(self, ignore_last_checkpoint=False, file_name=None):
        save_file = os.path.join(self.cfg.OUTPUT_DIR, "last_checkpoint")
        try:
            with open(save_file, "r") as last_checkpoint:
                f = last_checkpoint.read().strip()
        except IOError:
            self.logger.info("No checkpoint found. Initializing model from scratch")
            return {}

        if ignore_last_checkpoint:
            self.logger.info("Forced to Initialize model from scratch")
            return {}
        if file_name is not None:
            f = file_name

        self.logger.info("Loading checkpoint from {}".format(f))
        checkpoint = torch.load(f, map_location=torch.device("cpu"))
        for name, model in self.models.items():
            if name in checkpoint["models"]:
                model_dict = checkpoint["models"].pop(name)
                if model_dict is not None:
                    self.models[name].load_state_dict(model_dict, strict=False)
                else:
                    self.logger.warning("State dict for model \"%s\" is None " % name)
            else:
                self.logger.warning("No state dict for model: %s" % name)
        checkpoint.pop('models')
        if "optimizers" in checkpoint and self.optimizer:
            self.logger.info("Loading optimizer from {}".format(f))
            for name, optimizer in self.optimizer.items():
                self.optimizer[name].load_state_dict(checkpoint["optimizers"].pop(name))
        checkpoint.pop('optimizers')
        if "scheduler" in checkpoint and self.scheduler:
            self.logger.info("Loading scheduler from {}".format(f))
            self.scheduler.load_state_dict(checkpoint.pop("scheduler"))

        return checkpoint

    def tag_last_checkpoint(self, last_filename):
        save_file = os.path.join(self.cfg.OUTPUT_DIR, "last_checkpoint")
        with open(save_file, "w") as f:
            f.write(last_filename)