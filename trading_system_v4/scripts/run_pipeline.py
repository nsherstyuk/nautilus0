"""
Main pipeline script for Trading System v4.
Loads config, data, features, model, and runs signal generation.
"""
from config.config import get_config
from data.data_loader import load_csv
from features.feature_engineering import add_features
from model.model_inference import load_model, predict
from monitoring.logger import setup_logger

import os

def main():
    logger = setup_logger('pipeline')
    data_path = get_config('DATA_PATH', 'data/sample_data.csv')
    model_path = get_config('MODEL_PATH', 'model/model.pkl')
    logger.info(f'Loading data from {data_path}')
    df = load_csv(data_path)
    df = add_features(df)
    logger.info('Features added')
    model = load_model(model_path)
    logger.info('Model loaded')
    # Example: predict on last row
    features = df.iloc[-1].dropna().values
    signal = predict(model, features)
    logger.info(f'Predicted signal: {signal}')

if __name__ == '__main__':
    main()
