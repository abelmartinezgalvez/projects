import itertools
import scipy.sparse as sp
import numpy as np
import torch
from logging import Logger
from nnrecommend.logging import get_logger
from typing import Container, Dict
from bisect import bisect_left


class Dataset(torch.utils.data.Dataset):
    """
    basic dataset class
    """
    def __init__(self, interactions: np.ndarray, dtype=None):
        """
        :param interactions: 2d array with columns (user id, item id, context, label...)
        """
        interactions = np.array(interactions)
        if dtype:
            interactions = interactions.astype(dtype)
        assert len(interactions.shape) == 2 # should be two dimensions
        if interactions.shape[1] == 2:
            # if the interactions don't come with label column, create it with ones
            interactions = np.c_[interactions, np.ones(interactions.shape[0], interactions.dtype)]
        assert interactions.shape[1] > 2 # should have at least 3 columns

        self.__interactions = interactions
        self.idrange = None

    def denormalize_ids(self, mapping: Container[np.ndarray], remove_missing=True):
        """
        convert from normalized ids back to the original ones

        :param mapping: a container with each element a numpy array of raw ids in order
        """
        assert isinstance(mapping, (list, tuple))
        assert len(mapping) == self.__interactions.shape[1] - 1
        mapping = [np.array(v) for v in mapping]

        def find(container, val):
            if val < 0 or val >= len(container):
                return -1
            return container[int(val)]

        i = 0
        diff = 0
        for colmapping in mapping:
            for row in self.__interactions:
                row[i] = find(colmapping, row[i] - diff)
            diff += len(colmapping)
            i += 1
        
        if remove_missing:
            self.__remove_negative_ids()

        self.idrange = None


    def normalize_ids(self, mapping: Container[np.ndarray]=None, remove_missing=True) -> Container[np.ndarray]:
        """
        calculate a mapping for all the columns except the last one (label)
        so that the values are consecutive integers

        :param mapping: a container with each element a numpy array of raw ids in order
        """
        if isinstance(mapping, type(None)):
            mapping = []
            for i in range(self.__interactions.shape[1] - 1):
                ids = self.__interactions[:, i]
                mapping.append(np.sort(np.unique(ids)))
        else:
            assert isinstance(mapping, (list, tuple))
            assert len(mapping) + 1 == self.__interactions.shape[1]
            mapping = [np.array(v) for v in mapping]

        def find(container, val):
            idx = bisect_left(container, val)
            if idx < 0 or idx >= len(container) or container[idx] != val:
                return -1
            return idx

        i = 0
        diff = 0
        self.idrange = np.zeros(len(mapping), dtype=np.int64)
        for colmapping in mapping:
            for row in self.__interactions:
                row[i] = find(colmapping, row[i]) + diff
            diff += len(colmapping)
            self.idrange[i] = diff
            i += 1
        
        if remove_missing:
            self.__remove_negative_ids()

        return mapping

    def __remove_negative_ids(self):
        cond = (self.__interactions[:, :2] >= 0).all(axis=1)
        self.__interactions =  self.__interactions[cond]

    def __len__(self) -> int:
        return len(self.__interactions)

    def __getitem__(self, index) -> np.ndarray:
        return self.__interactions[index]

    def get_random_negative_row(self, row: np.ndarray) -> np.ndarray:
        row = np.array(row)
        assert self.idrange is not None
        assert row.shape[0] >= len(self.idrange)
        nrow = np.zeros(len(self.idrange) + 1)
        nrow[0] = row[0]
        for i in range(1, nrow.shape[0]-1):
            v = None
            minv, maxv = self.idrange[i-1:i+1]
            while v is None or v == row[i]:
                v = np.random.randint(minv, maxv, dtype=np.int64)
            nrow[i] = v
        return nrow

    def __row_comb_in_container(self, row: np.ndarray, container: Container) -> bool:
        row = np.array(row)
        for comb in itertools.combinations(row[:-1], 2):
            if comb in container:
                return True
        return False

    def get_random_negative_rows(self, container: Container, row: np.ndarray, num: int=1) -> np.ndarray:
        row = np.array(row)
        nrows = np.zeros((num, len(self.idrange) + 1))
        for i in range(num):
            nrow = None
            while nrow is None or self.__row_comb_in_container(nrow, container):
                nrow = self.get_random_negative_row(row)
            nrows[i] = nrow
        return nrows

    def add_negative_sampling(self, container: Container, num: int=1) -> None:
        """
        add negative samples to the dataset interactions
        with random ids that don't match existing interactions
        the negative samples will be placed in the rows immediately after the original one

        :param container: container to check if the interaction exists (usually the adjacency matrix)
        :param num: amount of samples per interaction
        """
        if num <= 0:
            return
        n = num + 1
        data = np.repeat(self.__interactions, n, axis=0)
        for i, row in enumerate(self.__interactions):
            data[1+n*i:n*(i+1), :] = self.get_random_negative_rows(container, row, num)
        self.__interactions = data

    def extract_test_dataset(self, num_user_interactions: int=1, min_keep_user_interactions: int=1) -> 'Dataset':
        """
        extract the last positive interaction of every user for the test dataset,
        check that the user has a minimum amount of interactions before extracting the last one

        :param num_user_interactions: amount of user interactions to extract to the test dataset
        :param min_keep_user_interactions: minimum amount of user interactions to keep in the original dataset
        """
        if self.idrange is None:
            self.normalize_ids()
        rowsbyuser = {}
        for i, row in enumerate(self.__interactions):
            if row[-1] <= 0:
                continue
            u = row[0]
            if u not in rowsbyuser:
                userrows = []
                rowsbyuser[u] = userrows
            else:
                userrows = rowsbyuser[u]
            userrows.append(i)
        rows = []
        for userrows in rowsbyuser.values():
            if len(userrows) < num_user_interactions + min_keep_user_interactions:
                continue
            rows += userrows[-num_user_interactions:]
        testset = Dataset(self.__interactions[rows])
        self.__interactions = np.delete(self.__interactions, rows, axis=0)
        testset.idrange = self.idrange
        return testset

    def create_adjacency_matrix(self) -> sp.spmatrix:
        """
        create the adjacency matrix for the dataset
        """
        if self.idrange is None:
            self.normalize_ids()
        size = self.idrange[1]
        matrix = sp.dok_matrix((size, size), dtype=np.int64)
        for row in self.__interactions:
            user, item = row[:2]
            matrix[user, item] = 1.0
            matrix[item, user] = 1.0
        return matrix

    def __remove_low(self, matrix: sp.spmatrix, lim: int, idx: int) -> None:
        if self.idrange is None:
            self.normalize_ids()
        counts = np.asarray(matrix.sum(0)).flatten()
        ids = self.__interactions[:, idx].astype(np.int64)
        cond = counts[ids] > lim
        self.__interactions =  self.__interactions[cond]
        return np.count_nonzero(cond == False)

    def remove_low(self, matrix: sp.spmatrix, lim: int) -> None:
        return self.remove_low_users(matrix, lim) + self.remove_low_items(matrix, lim)

    def remove_low_users(self, matrix: sp.spmatrix, lim: int) -> None:
        return self.__remove_low(matrix, lim, 0)

    def remove_low_items(self, matrix: sp.spmatrix, lim: int) -> None:
        return self.__remove_low(matrix, lim, 1)


class BaseDatasetSource:
    """
    basic class to load a dataset
    both trainset and testset should have the following structure
    (user id, item id, rating, context 1, context 2)

    user id, item id and context columns should be normalized,
    meaning that the values are consecutive and don't overlap

    item_info should be a dictionary with item_id keys
    and values should be a dictionary with the diferent decriptive fields
    """

    def __init__(self, logger: Logger=None):
        self._logger = logger or get_logger(self)
        self.trainset = None
        self.testset = None
        self.matrix = None
        self.item_info = None

    def load(self, max_interactions: int=-1):
        raise NotImplementedError()


def save_model(path: str, model, src: BaseDatasetSource):
    data = {
        "model": model,
        "idrange": src.trainset.idrange,
        "item_info": src.item_info
    }
    with open(path, "wb") as fh:
        torch.save(data, fh)