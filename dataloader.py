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

import pickle
import dareblopy as db
from threading import Thread, Lock, Event
import random
import threading

import numpy as np
import torch
import torch.tensor
import torch.utils
import torch.utils.data.dataloader
try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty
    import queue

cpu = torch.device('cpu')


class PickleDataset(torch.utils.data.Dataset):
    def __init__(self, cfg, logger, rank=0, data_train=None):
        self.cfg = cfg
        self.logger = logger
        self.last_data = ""
        if not data_train:
            self.data_train = []
            self.switch_fold(rank, 0)
        else:
            self.data_train = data_train

    def switch_fold(self, rank, lod):
        data_to_load = self.cfg.DATASET.PATH % (rank % self.cfg.DATASET.PART_COUNT, lod)

        if data_to_load != self.last_data:
            self.last_data = data_to_load
            self.logger.info("Switching data!")

            with open(data_to_load, 'rb') as pkl:
                self.data_train = pickle.load(pkl)

        self.logger.info("Train set size: %d" % len(self.data_train))
        self.data_train = self.data_train[:4 * (len(self.data_train) // 4)]
        self.data_train = np.asarray(self.data_train, dtype=np.uint8)

    def __getitem__(self, index):
        return self.data_train[index]

    def __len__(self):
        return len(self.data_train)


class TFRecordsDataset:
    def __init__(self, cfg, logger, rank=0, world_size=1, buffer_size_mb=200):
        self.cfg = cfg
        self.logger = logger
        self.rank = rank
        self.last_data = ""
        self.part_count = cfg.DATASET.PART_COUNT
        self.part_size = cfg.DATASET.SIZE // cfg.DATASET.PART_COUNT
        self.workers = []
        self.workers_active = 0
        self.iterator = None
        self.filenames = {}
        self.batch_size = 512
        self.features = {}

        assert self.part_count % world_size == 0

        self.part_count_local = cfg.DATASET.PART_COUNT // world_size

        for r in range(2, cfg.DATASET.MAX_RESOLUTION_LEVEL):
            files = []
            for i in range(self.part_count_local * rank, self.part_count_local * (rank + 1)):
                file = cfg.DATASET.PATH % (r, i)
                files.append(file)
            self.filenames[r] = files

        self.buffer_size_b = 1024 ** 2 * buffer_size_mb

        self.current_filenames = []

    def reset(self, lod, batch_size):
        assert lod in self.filenames.keys()
        self.current_filenames = self.filenames[lod]
        self.batch_size = batch_size

        img_size = 2 ** lod

        self.features = {
            # 'shape': db.FixedLenFeature([3], db.int64),
            'data': db.FixedLenFeature([3, img_size, img_size], db.uint8)
        }
        buffer_size = self.buffer_size_b // (3 * img_size * img_size)

        self.iterator = db.ParsedTFRecordsDatasetIterator(self.current_filenames, self.features, self.batch_size, buffer_size)

    def __iter__(self):
        return self.iterator

    def __len__(self):
        return self.part_count_local * self.part_size


class BatchCollator(object):
    def __init__(self, device=torch.device("cpu")):
        self.device = device

    def __call__(self, batch):
        with torch.no_grad():
            #x = np.asarray(batch, dtype=np.float32)
            x, = batch
            x = torch.tensor(x, requires_grad=True, device=torch.device(self.device), dtype=torch.float32)
            return x
