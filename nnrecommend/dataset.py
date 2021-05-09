import torch.utils.data
import scipy.sparse as sp
import numpy as np
from typing import Container


class Dataset(torch.utils.data.Dataset):
    """
    basic dataset class
    """
    def __init__(self, interactions: np.ndarray, iddiff: np.ndarray=None):
        """
        :param interactions: 2d array with columns (user id, item id, label, features...)
        :param iddiff: precalculated diff for the ids
        """

        interactions = np.array(interactions).astype(int)
        assert len(interactions.shape) == 2 # should be two dimensions
        if interactions.shape[1] == 2:
            # if the interactions don't come with label column, create it with ones
            interactions = np.c_[interactions, np.ones(interactions.shape[0], int)]
        assert interactions.shape[1] > 2 # should have at least 3 columns

        idmin = np.min(interactions[:, :2], axis=0)
        idmax = np.max(interactions[:, :2], axis=0)

        if isinstance(iddiff, type(None)):
            self.iddiff = -idmin
            self.iddiff[1] += idmax[0] - idmin[0] + 1
        else:
            iddiff = np.array(iddiff).astype(int)
            assert len(iddiff.shape) == 1
            assert iddiff.shape[0] == 2
            self.iddiff = iddiff

        self.idsize = idmax + self.iddiff + 1

        # adjust ids so that user ids start with 0 and item ids start after the last user id
        interactions[:, :2] += self.iddiff
        self.__interactions = interactions


    def __len__(self):
        return len(self.__interactions)

    def __getitem__(self, index):
        return self.__interactions[index]

    def __get_random_item(self) -> int:
        """
        return a valid random item id
        """
        return np.random.randint(self.idsize[0], self.idsize[1])

    def get_random_negative_item(self, user: int, item: int, container: Container) -> int:
        """
        return a random item id that meets certain conditions
        TODO: this method can produce infinite loops if there is no item that meets the requirements

        :param user: should not have an interaction with the given user
        :param item: should not be this item
        :param container: container to check if the interaction exists (usually the adjacency matrix)
        """
        j = self.__get_random_item()
        while j == item or (user, j) in container:
            j = self.__get_random_item()
        return j

    def add_negative_sampling(self, container: Container, num: int=1) -> None:
        """
        add negative samples to the dataset interactions
        with random item ids that don't match existing interactions
        the negative samples will be placed in the rows immediately after the original one

        :param container: container to check if the interaction exists (usually the adjacency matrix)
        :param num: amount of samples per interaction
        """
        if num <= 0:
            return

        shape = self.__interactions.shape
        data = np.zeros((shape[0]*(num+1), shape[1]), int)
        i = 0
        for row in self.__interactions:
            user, item = row[:2]
            data[i] = row
            i += 1
            for _ in range(num):
                nrow = data[i]
                nrow[:] = row
                nrow[1] = self.get_random_negative_item(user, item, container)
                nrow[2] = 0
                i += 1
        self.__interactions = data

    def create_adjacency_matrix(self) -> sp.dok_matrix:
        """
        create the adjacency matrix for the dataset
        """
        size = self.idsize[1]
        matrix = sp.dok_matrix((size, size), dtype=np.float32)
        for row in self.__interactions:
            user, item = row[:2]
            matrix[user, item] = 1.0
            matrix[item, user] = 1.0
        return matrix
