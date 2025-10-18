import os
from pathlib import Path


def project_tree(start_path='.', output_file='project_structure.txt',
                 max_depth=None, exclude=None, include_files=True):
    if exclude is None:
        exclude = {'.git', '__pycache__', '.idea', 'venv', 'env', '.pytest_cache'}

    start_path = Path(start_path)

    with open(output_file, 'w', encoding='utf-8') as f:

        def write_tree(directory, prefix="", depth=0):
            if max_depth and depth > max_depth:
                return

            # Получаем содержимое директории
            try:
                entries = sorted(os.listdir(directory))
            except PermissionError:
                return

            # Разделяем файлы и папки
            dirs = [e for e in entries if os.path.isdir(directory / e) and e not in exclude]
            files = [e for e in entries if os.path.isfile(directory / e) and e not in exclude] if include_files else []

            # Записываем директории
            for i, dir_name in enumerate(dirs):
                is_last_dir = (i == len(dirs) - 1) and (not files or not include_files)
                connector = "└── " if is_last_dir else "├── "
                f.write(f"{prefix}{connector}{dir_name}/\n")

                new_prefix = prefix + ("    " if is_last_dir else "│   ")
                write_tree(directory / dir_name, new_prefix, depth + 1)

            # Записываем файлы
            if include_files:
                for i, file_name in enumerate(files):
                    is_last = i == len(files) - 1
                    connector = "└── " if is_last else "├── "
                    f.write(f"{prefix}{connector}{file_name}\n")

        f.write(f"{start_path.name}/\n")
        write_tree(start_path)


# Использование
project_tree('.', 'structure.txt', max_depth=3)