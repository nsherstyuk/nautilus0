"""
Compare .env and .env.best files to show differences.
"""
from pathlib import Path
from difflib import unified_diff

def compare_env_files():
    """Compare .env and .env.best files."""
    
    env_file = Path(".env")
    env_best_file = Path(".env.best")
    
    if not env_file.exists():
        print("ERROR: .env file not found!")
        return
    
    if not env_best_file.exists():
        print("ERROR: .env.best file not found!")
        print("Run: python reconstruct_best_env.py")
        return
    
    # Read both files
    with open(env_file, 'r', encoding='utf-8') as f:
        env_lines = f.readlines()
    
    with open(env_best_file, 'r', encoding='utf-8') as f:
        env_best_lines = f.readlines()
    
    # Parse key-value pairs (ignore comments and empty lines)
    def parse_env_file(lines):
        """Parse env file into dict, ignoring comments and empty lines."""
        result = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                result[key.strip()] = value.strip()
        return result
    
    env_dict = parse_env_file(env_lines)
    env_best_dict = parse_env_file(env_best_lines)
    
    print("=" * 80)
    print("COMPARING .env vs .env.best")
    print("=" * 80)
    
    # Find differences
    all_keys = set(env_dict.keys()) | set(env_best_dict.keys())
    
    only_in_env = []
    only_in_best = []
    different_values = []
    same_values = []
    
    for key in sorted(all_keys):
        if key not in env_dict:
            only_in_best.append(key)
        elif key not in env_best_dict:
            only_in_env.append(key)
        elif env_dict[key] != env_best_dict[key]:
            different_values.append((key, env_dict[key], env_best_dict[key]))
        else:
            same_values.append(key)
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Total keys in .env: {len(env_dict)}")
    print(f"  Total keys in .env.best: {len(env_best_dict)}")
    print(f"  Same values: {len(same_values)}")
    print(f"  Different values: {len(different_values)}")
    print(f"  Only in .env: {len(only_in_env)}")
    print(f"  Only in .env.best: {len(only_in_best)}")
    
    # Show differences
    if different_values:
        print("\n" + "=" * 80)
        print("DIFFERENT VALUES:")
        print("=" * 80)
        for key, env_val, best_val in different_values:
            print(f"\n{key}:")
            print(f"  .env:      {env_val}")
            print(f"  .env.best: {best_val}")
    
    if only_in_env:
        print("\n" + "=" * 80)
        print("ONLY IN .env (not in .env.best):")
        print("=" * 80)
        for key in only_in_env:
            print(f"  {key}={env_dict[key]}")
    
    if only_in_best:
        print("\n" + "=" * 80)
        print("ONLY IN .env.best (not in .env):")
        print("=" * 80)
        for key in only_in_best:
            print(f"  {key}={env_best_dict[key]}")
    
    # Final verdict
    print("\n" + "=" * 80)
    if len(different_values) == 0 and len(only_in_env) == 0 and len(only_in_best) == 0:
        print("[OK] Files are IDENTICAL!")
    elif len(different_values) == 0 and len(only_in_best) == 0:
        print("[OK] All .env.best values are present in .env")
        print("     (some extra keys in .env, but that's OK)")
    else:
        print("[WARNING] Files are DIFFERENT!")
        print("\nTo use the optimal configuration:")
        print("  copy .env.best .env")
    print("=" * 80)

if __name__ == "__main__":
    compare_env_files()


