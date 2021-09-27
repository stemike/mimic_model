import os

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from modules.utils.pad_sequences import pad_sequences, filter_sequences
from modules.utils.handle_directories import dump_pickle, get_pickle_file_path


def wbc_criterion(x):
    return (x > 12 or x < 4) and x != 0


def temp_criterion(x):
    return (x > 100.4 or x < 96.8) and x != 0

def save_data_to_disk(self, whole_data, mask, name, labels, output_folder, n_targets=1):
    """
    Persist data to disk with pickle
    Parameters
    ----------
    whole_data: object
        dataset to be persisted
    mask: object
        boolean mask of which entry is padded
    name: str
        filenames
    labels: list[str]
        target column(s)
    output_folder:
        target folder for saved files
    n_targets: int
        number of targets
    """
    # Because the targets are for the same day shift the targets by one and ignore the last day
    # because no targets exist
    input_data = whole_data[:, :-1, :-n_targets]
    targets = whole_data[:, 1:, -n_targets:]
    targets = targets.reshape(targets.shape[0], targets.shape[1], n_targets)
    input_data_mask = mask[:, :-1, :-n_targets]
    targets_mask = mask[:, 1:, -n_targets:]
    targets_mask = targets_mask.reshape(targets_mask.shape[0], targets_mask.shape[1], n_targets)

    assert input_data.shape == input_data_mask.shape
    assert targets.shape == targets_mask.shape

    n_pos = np.count_nonzero(targets.sum(axis=1), axis=0)
    print(name)
    print(f'Number of positive patients {n_pos}')
    print(f'Number of neg patients {whole_data.shape[0] - n_pos}')

    dump_pickle(input_data, get_pickle_file_path(f'{name}_data', labels, output_folder))
    dump_pickle(targets, get_pickle_file_path(f'{name}_targets', labels, output_folder))
    dump_pickle(input_data_mask, get_pickle_file_path(f'{name}_data_mask', labels, output_folder))
    dump_pickle(targets_mask, get_pickle_file_path(f'{name}_targets_mask', labels, output_folder))


class MimicPreProcessor(object):
    """
    Creates Data Sets for Machine learning from a parsed mimic file
    """

    def __init__(self, mimic_file_path, id_col='hadm_id', random_seed=0):
        self.parsed_mimic = pd.read_csv(mimic_file_path)
        self.id_col = id_col
        self.random_seed = random_seed

    def create_target(self, targets):
        """
        Given a dataframe creates a specified target for it as well as deleting columns that make the task trivial
        Parameters
        ----------
        targets: list
            An array of targets
        Returns
        -------
        dataframe with target column(s) as well as a list of feature names
        """
        df = self.parsed_mimic.copy()
        # Delete features that make the task trivial
        trivial_features = ['subject_id', 'yob', 'admityear', 'ct_angio', 'infection', 'ckd']
        if 'MI' in targets:
            df['MI'] = ((df['troponin'] > 0.4) & (df['ckd'] == 0)).apply(lambda x: int(x))
            trivial_features += ['troponin', 'troponin_std', 'troponin_min', 'troponin_max']
        if 'SEPSIS' in targets:
            hr_sepsis = df['heart rate'].apply(lambda x: 1 if x > 90 else 0)
            respiratory_rate_sepsis = df['respiratory rate'].apply(lambda x: 1 if x > 20 else 0)
            wbc_sepsis = df['wbcs'].apply(wbc_criterion)
            temperature_f_sepsis = df['temperature (f)'].apply(temp_criterion)
            sepsis_points = (hr_sepsis + respiratory_rate_sepsis + wbc_sepsis + temperature_f_sepsis)
            df['SEPSIS'] = ((sepsis_points >= 2) & (df['infection'] == 1)).apply(lambda x: int(x))
        if 'VANCOMYCIN' in targets:
            df['VANCOMYCIN'] = df['vancomycin'].apply(lambda x: 1 if x > 0 else 0)
            trivial_features += ['vancomycin']

        df = df.drop(trivial_features, axis=1, errors='ignore')
        df = df.select_dtypes(exclude=['object'])

        print(f'Created target {targets}')

        return df

    def reduce_features(self, train_data, test_data):
        """
        Standardizes train and test data as well as applying PCA
        Parameters
        ----------
        train_data:
            The training data
        test_data:
            The test data

        Returns
        -------
        Transformed data
        """
        # +1 to also exclude the id col
        means = train_data.mean(axis=0)
        stds = train_data.std(axis=0)
        stds[stds == 0] = 1

        train_data = (train_data - means) / stds
        test_data = (test_data - means) / stds

        pca = PCA(n_components=0.99, random_state=self.random_seed)
        pca.fit(train_data.values)
        train_data_transformed = pca.transform(train_data.values)
        test_data_transformed = pca.transform(test_data.values)

        print(f'Can explain {np.sum(pca.explained_variance_ratio_)} variance')
        print(f'Reduced number of features from {train_data.shape[1]} to {train_data_transformed.shape[1]}')

        return pd.DataFrame(train_data_transformed, index=train_data.index), \
               pd.DataFrame(test_data_transformed, index=test_data.index)

    def balance_data_set(self, train_data, n_targets, undersample=True, imbalance=1.5):
        """
        Balances data set by under or oversampling
        Parameters
        ----------
        train_data: object
            training data
        n_targets: int
            number of targets
        undersample: bool
            whether to under or oversample
        imbalance: float
            amount of imbalance to keep

        Returns
        -------
        Balanced data
        """
        # Get the number of patients with at least one positive day for each target then take the sum
        patients_grouped = train_data.groupby(self.id_col)
        n_pos_per_patient = patients_grouped.agg('sum').iloc[:, -n_targets:]
        n_pos_per_patient = n_pos_per_patient - patients_grouped.first().iloc[:, -n_targets:]

        if undersample:
            n_rows = (n_pos_per_patient != 0).sum(axis=0).argmax()
        else:
            n_rows = (n_pos_per_patient != 0).sum(axis=0).argmin()

        pos_ids = np.array(n_pos_per_patient[n_pos_per_patient.iloc[:, n_rows] != 0].index)
        neg_rows = n_pos_per_patient[n_pos_per_patient.iloc[:, n_rows] == 0].sum(axis=1)
        neg_pos_ids = np.array(neg_rows[neg_rows != 0].index)  # Neg in i_target but pos in other targets
        neg_ids = np.array(neg_rows[neg_rows == 0].index)

        np.random.shuffle(pos_ids)
        np.random.shuffle(neg_pos_ids)
        np.random.shuffle(neg_ids)

        print(len(neg_pos_ids), len(neg_ids))
        neg_ids = np.concatenate([neg_pos_ids, neg_ids])

        if pos_ids.shape[0] < neg_ids.shape[0]:
            minority_class = pos_ids
            majority_class = neg_ids
        else:
            minority_class = neg_ids
            majority_class = pos_ids
        minority_length = minority_class.shape[0]

        if undersample:
            total_ids = np.hstack([minority_class[:minority_length], majority_class[:int(minority_length * imbalance)]])
            np.random.shuffle(total_ids)
            train_data = train_data[train_data[self.id_col].isin(total_ids)]
            print(f'{n_rows=} {len(pos_ids)=} - {len(neg_ids)=} - {len(total_ids)=}')
            print('Balanced training data by undersampling')
        else:
            difference = majority_class.shape[0] // minority_length
            minority_data = train_data[train_data[self.id_col].isin(minority_class)]
            for i in range(difference - 1):
                train_data = train_data.append(minority_data)
            print(f'Added minority class {difference - 1} times')
            print('Balanced training data by oversampling')
        return train_data

    def split_and_normalize_data(self, df, train_percentage, reduce_features=True, balance_set=True, n_targets=1):
        """
        Splits data into train and test set. Then applies normalization as well as undersampling (if specified)
        Parameters
        ----------
        df: object
            data to be split into train and test set
        train_percentage: float
            percentage of training samples
        reduce_features: bool
            whether or not to reduce the number of features
        balance_set: bool
            whether to balance the data
        n_targets: int
            number of targets

        Returns
        -------
        train and test set
        """
        print(f'{self.random_seed=} {train_percentage=}')
        np.random.seed(self.random_seed)
        keys = df[self.id_col].sample(frac=1, random_state=self.random_seed).unique()
        train_bound = int(train_percentage * len(keys))
        train_keys = keys[:train_bound]
        test_keys = keys[train_bound:]
        train_data = df[df[self.id_col].isin(train_keys)]
        test_data = df[df[self.id_col].isin(test_keys)]

        if reduce_features:
            train_subset = train_data.iloc[:, :-(n_targets + 1)]
            test_subset = test_data.iloc[:, :-(n_targets + 1)]
            train_subset, test_subset = self.reduce_features(train_subset, test_subset)
            train_data = pd.concat([train_subset, train_data.iloc[:, -(n_targets + 1):]], axis=1)
            test_data = pd.concat([test_subset, test_data.iloc[:, -(n_targets + 1):]], axis=1)

        if balance_set:
            train_data = self.balance_data_set(train_data, n_targets)

        print(f'{train_data.shape=} - {test_data.shape=}')

        if np.isnan(train_data).any().any():
            raise Exception('NaN Values remain in Train data')
        if np.isnan(test_data).any().any():
            raise Exception('NaN Values remain in Test data')

        return train_data, test_data

    def pad_data(self, df, time_steps, pad_value=0):
        """
        Pad dataframe and create boolean mask
        Parameters
        ----------
        df: object
            dataframe to be padded
        time_steps: int
            number of time steps to pad up to
        pad_value: float
            value with which the entry will get padded
        Returns
        -------
        padded data and boolean mask
        """
        df = pad_sequences(df, time_steps, pad_value=pad_value, grouping_col=self.id_col)
        df = df.drop(columns=[self.id_col])
        whole_data = df.values
        whole_data = whole_data.reshape(int(whole_data.shape[0] / time_steps), time_steps, whole_data.shape[1])

        # creating a second order bool matrix which keeps track of padded entries
        mask = (~whole_data.any(axis=2))
        whole_data[mask] = np.nan
        # restore 3D shape to boolmatrix for consistency
        mask = np.isnan(whole_data)
        whole_data[mask] = pad_value
        print("Padded data frame")
        return whole_data, mask

    def apply_pipeline(self, targets, n_time_steps, output_folder, balance_set=True, reduce_features=False):
        """
        Run a pipeline that:
            creates the target column target
            splits the data into train, validation and test set
            Padds the entry to n_time_steps
            Persists the data onto the disk to output_folder
        Parameters
        ----------
        targets: list
            target column(s)
        n_time_steps: int
            number of time steps
        output_folder: str
            target folder for saved files
        reduce_features: bool
            whether or not to reduce the number of features
        balance_set: bool
            whether to balance the data
        """
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        df = self.create_target(targets)
        df = filter_sequences(df, 2, n_time_steps, grouping_col=self.id_col)
        train, test = self.split_and_normalize_data(df, train_percentage=0.8, n_targets=len(targets),
                                                    balance_set=balance_set, reduce_features=reduce_features)

        feature_names = list(train.columns[:-len(targets)])
        feature_names.remove(self.id_col)
        dump_pickle(feature_names, get_pickle_file_path('features', targets, output_folder))

        for dataset, name in [(train, 'train'), (test, 'test')]:
            whole_data, mask = self.pad_data(dataset, time_steps=n_time_steps)
            save_data_to_disk(whole_data, mask, name, targets, output_folder, n_targets=len(targets))

        print(f'Saved files to folder: {output_folder}')
