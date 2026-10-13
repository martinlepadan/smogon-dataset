"""What the monthly update asks Kaggle: is this dataset there, give me its files, take this new version."""

from pathlib import Path

from smogon_dataset.cards import OWNER


class UploadRefusedError(Exception):
    pass


class KaggleDatasets:
    def __init__(self) -> None:
        # Importing kaggle logs in, and prints a help page when it finds no credentials:
        # not something every other command should go through.
        from kaggle.api.kaggle_api_extended import KaggleApi  # noqa: PLC0415

        self._api = KaggleApi()
        self._api.authenticate()

    def exists(self, slug: str) -> bool:
        # Asking for a dataset that is not there answers 403, same as a token without the
        # rights: only the listing tells the two apart. The search is loose, hence the exact match.
        page = 1
        while found := self._api.dataset_list(user=OWNER, search=slug, page=page):
            if any(dataset.ref == f"{OWNER}/{slug}" for dataset in found):
                return True
            page += 1
        return False

    def fetch_file(self, slug: str, name: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        self._api.dataset_download_file(f"{OWNER}/{slug}", name, path=str(dest_dir), force=True)
        return dest_dir / name

    def fetch_all(self, slug: str, dest_dir: Path) -> None:
        dest_dir.mkdir(parents=True, exist_ok=True)
        self._api.dataset_download_files(f"{OWNER}/{slug}", path=str(dest_dir), force=True, unzip=True)

    def send(self, dataset_dir: Path, notes: str, *, create: bool = False) -> None:
        """Upload every file of `dataset_dir` as a new version, or as a new public dataset.

        A version only holds the files sent with it, so the folder must be the whole dataset.
        """
        # Folders go up as one zip each, which Kaggle unpacks. The kaggle command prints a
        # refusal and still exits 0, so the answer is read here.
        if create:
            answer = self._api.dataset_create_new(str(dataset_dir), public=True, convert_to_csv=False, dir_mode="zip")
        else:
            answer = self._api.dataset_create_version(str(dataset_dir), notes, convert_to_csv=False, dir_mode="zip")
        if answer.status.lower() != "ok":
            raise UploadRefusedError(f"Kaggle refused {dataset_dir.name}: {answer.error}")
