import time
from modules.classes.mimic_parser import MimicParser
from modules.classes.mimic_pre_processor import MimicPreProcessor
from modules.experiment_config import get_targets, get_percentages, get_seeds, get_mimic_version, get_window_size, \
    get_random_seed, get_train_single_targets, get_train_comparison
from modules.load_data import load_data_sets, get_pickle_folder
from modules.models.attention_models import AttentionLSTM
from modules.models.comparison_models import ComparisonLSTM, ComparisonFNN, ComparisonLogisticRegression
from modules.models.hopfield_models import HopfieldLayerModel, HopfieldPoolingModel, HopfieldLookupModel, HopfieldLSTM
from modules.train_model import train_model, train_xgb


def train_models(mimic_version, data_path, n_time_steps, random_seed, targets, train_comparison):
    """
    Training loop for training models with targets and percentages
    @param mimic_version: which mimic version to use 3 or 4
    @param data_path: path to data for the experiments
    @param n_time_steps: number of time step for one sample
    @param random_seed: seed for setting random functions
    @param targets:
    @param train_comparison: whether to train for NN-LSTM comparison or benchmark experiment
    """
    start_time = time.time()
    print(f'{data_path=}')
    n_targets = len(targets)
    print(f'\nTarget: {targets}')
    for p in get_percentages():
        print(f'Percentage: {p}')
        train_dataset, n_features = load_data_sets(data_path, targets, p)
        common_model_id = f'_{mimic_version}_{targets}_{n_time_steps}_{random_seed}'
        if train_comparison:
            train_dataset_reduced, n_features_reduced = load_data_sets(data_path, targets, p, reduce_dimensions=True)
            models = [
                ('comparison_LR', ComparisonLogisticRegression(n_features_reduced, num_targets=n_targets)),
                ('comparison_FNN', ComparisonFNN(n_features_reduced, num_targets=n_targets)),
                ('comparison_LSTM', ComparisonLSTM(n_features, num_targets=n_targets))]
            if len(targets) == 1: #If not Multitasking
                model_id = 'xgb' + common_model_id
                train_xgb(model_id, train_dataset_reduced, seed=random_seed)
                model_id = 'random_forest_xgb' + common_model_id
                train_xgb(model_id, train_dataset_reduced, nbr=1, lr=1, npt=100, seed=random_seed)
        else:
            models = [
                ('partial_attention_LSTM', AttentionLSTM(n_features, full_attention=False, num_targets=n_targets)),
                ('full_attention_LSTM', AttentionLSTM(n_features, full_attention=True, num_targets=n_targets)),
                ('partial_hopfield_LSTM', HopfieldLSTM(n_features, full_attention=False, num_targets=n_targets)),
                ('full_hopfield_LSTM', HopfieldLSTM(n_features, full_attention=True, num_targets=n_targets)),
                ('hopfield_layer', HopfieldLayerModel(n_features, num_targets=n_targets)),
                ('hopfield_pooling', HopfieldPoolingModel(n_features, num_targets=n_targets)),
                ('hopfield_lookup', HopfieldLookupModel(n_features, int(len(train_dataset) / 10000), num_targets=n_targets))
            ]

        for model_name, model in models:
            model_id = model_name + common_model_id
            if model_name == 'comparison_FNN' or model_name == 'comparison_LR':
                train_model(model_id, model, train_dataset_reduced, targets, seed=random_seed)
            else:
                train_model(model_id, model, train_dataset, targets, seed=random_seed)

        print(f'\rFinished training on {p * 100}% of data')
    print(f'\rFinished training on {random_seed=}')
    end_time = time.time()
    print(f'{end_time - start_time} seconds needed for training')


def main(parse_mimic, pre_process_data, create_models):
    """
    Main loop that process mimic db, preprocess data and trains models
    @param random_seed: random seed
    @param parse_mimic: whether to parse the mimic database
    @param pre_process_data: whether to preprocess the parsed the mimic database
    @param create_models: whether to train the models
    @param mimic_version: which mimic version to use 3 or 4
    @param window_size: number of hours for one time step
    """

    mimic_version = get_mimic_version()
    window_size = get_window_size()
    random_seed = get_random_seed()
    print('Start Program')
    print(f'Mimic Version {mimic_version}')
    original_mimic_folder = f'./data/mimic_{mimic_version}_database'
    parsed_mimic_folder = f'mapped_elements_ws_{window_size}'
    file_name = 'CHARTEVENTS'
    id_col = 'ITEMID'
    label_col = 'LABEL'

    mimic_parser = MimicParser(original_mimic_folder, parsed_mimic_folder, file_name, id_col, label_col, mimic_version,
                               window_size)

    # Parse Mimic
    if parse_mimic:
        print('Parse Mimic Data')
        mimic_parser.perform_full_parsing()

    n_time_steps = int((24 // window_size) * 14)
    pickled_data_path = get_pickle_folder(mimic_version, n_time_steps, random_seed)

    targets = get_targets()
    # Preprocess Mimic
    if pre_process_data:
        print('Preprocess Data')
        if mimic_version == 3:
            parsed_mimic_filepath = mimic_parser.an_path + '.csv'
        else:
            parsed_mimic_filepath = mimic_parser.aii_path + '.csv'

        mimic_pre_processor = MimicPreProcessor(parsed_mimic_filepath, random_seed=random_seed)

        print(f'Creating Datasets for {targets}')
        mimic_pre_processor.pre_process_and_save_files(targets, n_time_steps, pickled_data_path)
        for target in targets:
            mimic_pre_processor.pre_process_and_save_files([target], n_time_steps, pickled_data_path)
        print(f'Created Datasets for {targets}\n')

    if create_models:
        train_models(mimic_version, pickled_data_path, n_time_steps, random_seed, targets, get_train_comparison())
        if get_train_single_targets() and len(targets) > 1:
            for target in targets:
                train_models(mimic_version, pickled_data_path, n_time_steps, random_seed, [target], get_train_comparison())


if __name__ == "__main__":
    parse = False
    pre_process = False
    train = True

    main(parse, pre_process, train)
