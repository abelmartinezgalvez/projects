from logging import Logger
import pandas as pd
import numpy as np
from nnrecommend.dataset.movielens import LOAD_COLUMNS
from nnrecommend.hparams import HyperParameters
from nnrecommend.dataset import BaseDatasetSource, InteractionDataset, IdGenerator


MIN_ITEM_INTERACTIONS = 1
MIN_USER_INTERACTIONS = 3


class SpotifyDatasetSource(BaseDatasetSource):
    """
    the dataset can be downloaded from https://aicrowd-production.s3.eu-central-1.amazonaws.com/dataset_files/challenge_25/0654d015-d4b4-4357-8040-6a846dec093d_training_set_track_features_mini.tar.gz
    with modifications in the dataset to have skipped and previous_song columns already how we want them
    """
    def __init__(self, path: str, logger: Logger=None):
        super().__init__(logger)
        self.__path = path

    def __load_data(self, maxsize: int, load_skip: True, load_prev: True):
        nrows = maxsize if maxsize > 0 else None
        cols = ["user_id", "song_id"]
        if load_skip:
            cols.append("skipped")
        if load_prev:
            cols.append("previous_song")
        data = pd.read_csv(self.__path, sep=',', nrows=nrows, usecols=cols)

        data = np.array(data[cols], dtype=np.int64)
        labels = np.ones(data.shape[0]) # add label column with ones
        data = np.insert(data, data.shape[1], labels, axis=1)
    
        return data

    def load(self, hparams: HyperParameters) -> None:
        maxsize = hparams.max_interactions
        self._logger.info("loading data...")
        load_skip = hparams.should_have_interaction_context("skip")
        load_prev = hparams.should_have_interaction_context("previous")
        self.trainset = InteractionDataset(self.__load_data(maxsize, load_skip, load_prev))
        self._logger.info("normalizing ids...")
        mapping = self.trainset.normalize_ids()
        self._logger.info("calculating adjacency matrix...")
        self.matrix = self.trainset.create_adjacency_matrix()
        self._logger.info("removing low interactions...")
        ci = self.trainset.remove_low_items(self.matrix, MIN_ITEM_INTERACTIONS)
        cu = self.trainset.remove_low_users(self.matrix, MIN_USER_INTERACTIONS)
        recalc = cu > 0 or ci > 0
        if recalc:
            self._logger.info(f"removed {cu} users and {ci} items")
            self._logger.info("normalizing ids again...")
            self.trainset.denormalize_ids(mapping)
            mapping = self.trainset.normalize_ids()
            self._logger.info("calculating adjacency matrix again...")
            self.matrix = self.trainset.create_adjacency_matrix()
        self._logger.info("extracting test dataset..")
        self.testset = self.trainset.extract_test_dataset()


class SpotifyRawDatasetSource(BaseDatasetSource):
    """
    the dataset can be downloaded from https://aicrowd-production.s3.eu-central-1.amazonaws.com/dataset_files/challenge_25/0654d015-d4b4-4357-8040-6a846dec093d_training_set_track_features_mini.tar.gz
    """
    COLUMNS = ("session_id", "track_id_clean", "session_position")
    SKIP_COLUMNS = ("skip_1", "skip_2", "skip_3", "not_skipped")
    USER_COLUMN = "session_id"
    ITEM_COLUMN = "track_id_clean"
    SORT_COLUMN = 'session_position'
    MIN_REPEAT = 2
    MIN_SKIP = 3

    def __init__(self, path: str, logger: Logger=None):
        super().__init__(logger)
        self.__path = path

    def __load_data(self, maxsize: int, load_skip: False) -> np.ndarray:
        nrows = maxsize if maxsize > 0 else None

        cols = self.COLUMNS + self.SKIP_COLUMNS if load_skip else self.COLUMNS
        data = pd.read_csv(self.__path, sep=',', nrows=nrows, usecols=cols)
        data.sort_values(by=self.SORT_COLUMN, inplace=True, ascending=True)
        del data[self.SORT_COLUMN]

        idcols = (self.USER_COLUMN, self.ITEM_COLUMN)
        for colname in idcols:
            gen = IdGenerator()
            data[colname].apply(gen.add)
            data[colname] = data[colname].apply(gen.find)

        if load_skip:
            def get_skip_value(series):
                c = 0
                for i, v in enumerate(series):
                    if v:
                        break
                    c += 1
                return c
            cols = list(self.SKIP_COLUMNS)
            data['skip'] = data[cols].apply(get_skip_value, axis=1)
            data = data.drop(cols, axis=1)
            data.value_counts(subset=['num_legs', 'num_wings'], sort=False)

        data = np.array(data, dtype=np.int64)
        labels = np.ones(data.shape[0]) # add ones as labels
        data = np.insert(data, data.shape[1], labels, axis=1)
        return data

    def __fix_skip(self, dataset: InteractionDataset):
        """
        convert skip column into
        -1 * item_id: if skipped < MIN_SKIP or counts < MIN_REPEAT
        1 * item_id: else (good item)
        """
        self._logger.info("fixing skip values...")
        repeats = (self.trainset.get_counts() >= self.MIN_REPEAT)
        noskips = self.trainset[:, 2] >= self.MIN_SKIP
        factor = np.logical_or(repeats, noskips).astype(np.int64) * 2 - 1
        self.trainset[:, 2] = factor * self.trainset[:, 1]

    def load(self, hparams: HyperParameters) -> None:
        maxsize = hparams.max_interactions
        self._logger.info("loading spotify data...")
        load_skip = hparams.should_have_interaction_context("skip")
        self.trainset = InteractionDataset(self.__load_data(maxsize, load_skip))
        if load_skip:
            self.__fix_skip(self.trainset)
        self._logger.info("normalizing ids...")
        mapping = self.trainset.normalize_ids()
        self._logger.info("calculating adjacency matrix...")
        self.matrix = self.trainset.create_adjacency_matrix()
        self._logger.info("removing low interactions...")
        ci = self.trainset.remove_low_items(self.matrix, MIN_ITEM_INTERACTIONS)
        cu = self.trainset.remove_low_users(self.matrix, MIN_USER_INTERACTIONS)
        recalc = cu > 0 or ci > 0
        if recalc:
            self._logger.info(f"removed {cu} users and {ci} items")
            self._logger.info("normalizing ids again...")
            self.trainset.denormalize_ids(mapping)
            mapping = self.trainset.normalize_ids()
        if hparams.should_have_interaction_context("previous"):
            self._logger.info("adding previous item column...")
            self.trainset.add_previous_item_column()
        if recalc:
            self._logger.info("calculating adjacency matrix again...")
            self.matrix = self.trainset.create_adjacency_matrix()
        self._logger.info("extracting test dataset..")
        self.testset = self.trainset.extract_test_dataset()