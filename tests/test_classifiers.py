"""Regression checks for the copied notebook algorithms and CSV workflow."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

from embryo_analyser.classifiers import load_bundle, predict_files, save_bundle, train_models
from embryo_analyser.preprocessing import (
    fit_preprocessing, infer_label, read_measurements, transform_files,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "dataset" / "raw_dataset"
TRAIN = RAW / "gap43-mCherry" / "train"


class ClassifierWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.train_paths = sorted(TRAIN.rglob("*.csv"))
        if not cls.train_paths:
            raise unittest.SkipTest("Optional local experimental CSV fixtures are not available.")
        cls.bundle = train_models(cls.train_paths)
        cls.test_paths = sorted((RAW / "gap43-mCherry" / "test").rglob("*.csv"))

    def test_real_csv_single_and_batch_predictions_match(self):
        batch = predict_files(self.bundle, self.test_paths)
        self.assertEqual(len(batch), 2)
        for path in self.test_paths:
            single = predict_files(self.bundle, path)
            expected = batch[batch.source_csv == str(path.resolve())].reset_index(drop=True)
            pd.testing.assert_frame_equal(single, expected)
        self.assertTrue(batch.retained_cells.gt(0).all())
        self.assertTrue(batch.rf_prediction.isin([0, 1]).all())
        self.assertTrue(batch.svm_prediction.isin([0, 1]).all())

    def test_notebook_preprocessing_regression(self):
        # Execute original transformation cells, independently of new helpers.
        reference = json.loads((ROOT / "tests/fixtures/legacy_preprocessing.json").read_text(encoding="utf-8"))
        class FixedInputDirectory:
            def rglob(directory, pattern):
                return iter(self.train_paths)

        namespace = {"pd": pd, "np": np, "Path": Path,
                     "reference_directory": FixedInputDirectory(),
                     "gap43": "gap43-mCherry", "ecad": "E-CadGFP"}
        read_source = reference["cells"]["2"]
        read_source = read_source.replace('Path("./raw_dataset")', "reference_directory")
        exec(read_source, namespace)
        exec(reference["cells"]["3"], namespace)
        frame = namespace["df"]
        actual_frame, _ = read_measurements(self.train_paths, require_labels=True)
        pd.testing.assert_frame_equal(actual_frame, frame.reset_index(drop=True))
        namespace["cols"] = frame.columns.drop(["EM", "strain", "label"])
        for cell in (10, 13, 14, 23, 24):
            if cell == 13:
                namespace["corr_matrix"] = namespace["df_copy"][namespace["cols"]].corr(method="pearson")
            exec(reference["cells"][str(cell)], namespace)
        expected = namespace["make_bins"](namespace["reduced_df"])
        state, actual, _ = fit_preprocessing(self.train_paths)
        self.assertEqual(state.feature_columns, tuple(namespace["reduced_cols"]))
        pd.testing.assert_frame_equal(actual, expected)
        for column in state.feature_columns:
            np.testing.assert_array_equal(state.bin_edges[column], namespace["bin_dict"][column])
            np.testing.assert_allclose(actual.filter(like=column + "_bin_").sum(axis=1), 100)

    def test_notebook_classifier_parameters_and_selection_regression(self):
        profiles = self.bundle.training_profiles
        labels = self.bundle.training_labels
        # Original cells 28–34 and 36–41, including their final refits.
        rf = RandomForestClassifier(n_estimators=100, max_depth=2, max_features=0.3,
                                    min_samples_leaf=2, random_state=114514)
        rf.fit(profiles, labels)
        importance = pd.DataFrame([rf.feature_importances_ * 100], columns=profiles.columns)
        importance.drop(columns=[column for column in importance if importance[column][0] < 5], inplace=True)
        rf.fit(profiles[importance.columns], labels)
        self.assertEqual(self.bundle.selected_columns["rf"], tuple(importance.columns))
        np.testing.assert_array_equal(rf.predict(profiles[importance.columns]),
                                      self.bundle.models["rf"].predict(profiles[importance.columns]))
        scaler = StandardScaler()
        scaled = pd.DataFrame(scaler.fit_transform(profiles), columns=profiles.columns)
        svm = LinearSVC(penalty="l2", C=1, dual="auto", random_state=0)
        svm.fit(scaled, labels)
        normal = svm.coef_[0]
        normal = normal / np.sqrt(sum(value ** 2 for value in normal))
        importance = pd.DataFrame([[100 * value ** 2 for value in normal]], columns=profiles.columns)
        importance.drop(columns=[column for column in importance if importance[column][0] < 5], inplace=True)
        svm.fit(scaled[importance.columns], labels)
        self.assertEqual(self.bundle.selected_columns["svm"], tuple(importance.columns))
        np.testing.assert_array_equal(svm.predict(scaled[importance.columns]),
                                      self.bundle.models["svm"].predict(scaled[importance.columns]))

    def test_model_save_and_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = save_bundle(self.bundle, Path(temporary) / "nested" / "models.joblib")
            restored = load_bundle(destination)
            pd.testing.assert_frame_equal(predict_files(self.bundle, self.test_paths),
                                          predict_files(restored, self.test_paths))

    def test_model_output_inside_dataset_is_rejected_before_writing(self):
        destination = RAW / "forbidden-test-model.joblib"
        self.assertFalse(destination.exists())
        with self.assertRaisesRegex(ValueError, "inside dataset"):
            save_bundle(self.bundle, destination)
        self.assertFalse(destination.exists())

    def test_all_real_csvs_match_original_feature_and_cleaning_totals(self):
        all_paths = sorted(RAW.rglob("*.csv"))
        frame, info = read_measurements(all_paths, require_labels=True)
        state, profiles, _ = fit_preprocessing(all_paths)
        self.assertEqual(len(all_paths), 24)
        self.assertEqual(len(frame), 2523)
        self.assertEqual(int(info.retained_cells.sum()), 2523)
        self.assertEqual(len(profiles), 24)
        self.assertEqual(state.feature_columns, ("Area", "Angle", "Circ.", "Solidity"))

    def test_prediction_does_not_require_label_or_strain_in_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "embryo.csv"
            source = pd.read_csv(self.test_paths[0])
            source.to_csv(path, index=False)
            prediction = predict_files(self.bundle, path)
            self.assertTrue(pd.isna(prediction.loc[0, "true_label"]))
            labelled = predict_files(self.bundle, self.test_paths[0])
            for model in ("rf", "svm"):
                self.assertEqual(prediction.loc[0, model + "_prediction"],
                                 labelled.loc[0, model + "_prediction"])

    def test_incidental_path_names_do_not_create_truth_labels(self):
        reference = predict_files(self.bundle, self.test_paths[0])
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("quality_control", "control_mutant_comparison"):
                with self.subTest(directory=name):
                    directory = Path(temporary) / name
                    directory.mkdir()
                    path = directory / "embryo.csv"
                    pd.read_csv(self.test_paths[0]).to_csv(path, index=False)
                    prediction = predict_files(self.bundle, path)
                    self.assertTrue(pd.isna(prediction.loc[0, "true_label"]))
                    for model in ("rf", "svm"):
                        self.assertEqual(prediction.loc[0, model + "_prediction"],
                                         reference.loc[0, model + "_prediction"])
                    with self.assertRaisesRegex(ValueError, "Missing training label"):
                        fit_preprocessing(path)

    def test_truth_labels_require_explicit_path_components(self):
        for path, expected in (
            ("inputs/control.csv", 0),
            ("inputs/mutant.csv", 1),
            ("inputs/control/embryo.csv", 0),
            ("inputs/mutant/embryo.csv", 1),
            ("inputs/control-gap43mCherry/embryo.csv", 0),
            ("inputs/mutant-sdkMB5054/embryo.csv", 1),
            ("inputs/quality_control/embryo.csv", None),
            ("inputs/control_mutant_comparison/embryo.csv", None),
            ("inputs/embryo_control.csv", None),
        ):
            with self.subTest(path=path):
                self.assertEqual(infer_label(path), expected)

    def test_missing_columns_and_no_retained_cells_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pd.read_csv(self.test_paths[0])
            missing = Path(temporary) / "missing.csv"
            source.drop(columns=["Area"]).to_csv(missing, index=False)
            with self.assertRaisesRegex(ValueError, "Missing measurement columns"):
                predict_files(self.bundle, missing)
            empty = Path(temporary) / "empty.csv"
            source["AR"] = 1.5
            source.to_csv(empty, index=False)
            with self.assertRaisesRegex(ValueError, "No valid cells"):
                predict_files(self.bundle, empty)

    def test_all_values_outside_training_bins_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = pd.read_csv(self.test_paths[0])
            source["Area"] = self.bundle.preprocessing.bin_edges["Area"][-1] + 1
            path = Path(temporary) / "outside.csv"
            source.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "outside the training bin range"):
                transform_files(self.bundle.preprocessing, path)

    def test_empty_input_and_invalid_model_are_errors(self):
        with self.assertRaisesRegex(ValueError, "At least one"):
            predict_files(self.bundle, [])
        with self.assertRaisesRegex(ValueError, "model must"):
            train_models(self.train_paths, model="unknown")
        with self.assertRaisesRegex(ValueError, "both control"):
            train_models([path for path in self.train_paths if "control" in str(path)])
        with self.assertRaisesRegex(ValueError, "no features"):
            train_models(self.train_paths, model="rf", importance_threshold=100)

    def test_training_requires_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = []
            for i, source_path in enumerate(self.test_paths):
                path = Path(temporary) / f"embryo-{i}.csv"
                pd.read_csv(source_path).to_csv(path, index=False)
                paths.append(path)
            with self.assertRaisesRegex(ValueError, "Missing training label"):
                train_models(paths)
            state, profiles, labels = fit_preprocessing(paths, labels=[0, 1])
            np.testing.assert_array_equal(labels, [0, 1])
            self.assertEqual(len(profiles), 2)
            self.assertEqual(state.num_bins, 16)


if __name__ == "__main__":
    unittest.main()
