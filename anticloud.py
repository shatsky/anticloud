#!/usr/bin/env python3
import os, sys, filecmp

# src and dst semantics
# src is tree in which:
# - normally there are fewer files (old backup vs new backup, backup vs accumulator)
# - normally files persist, src in `cp -l src dst`
# - source of trust
# - iterated
# - older
# dst is tree in which:
# - normally there are more files
# - normally files are replaced with hardlinks to src, dst in `cp -l src dst`
# - target of deduplication
# - newer

# default: fail
# "force": replace dst
# "swap": swap dst and src if src is single, else fail
CONFIG_DST_HARDLINK_COUNT_MULTIPLE = os.getenv('ANTICLOUD_DST_HARDLINK_COUNT_MULTIPLE')
# default: fail
# "force": replace dst
# "setonsrc": copy val of dst mtime and set it on src
CONFIG_DST_MTIME_OLDER =             os.getenv('ANTICLOUD_DST_MTIME_OLDER')
# 1: skip write ops
# default, 0: perform write ops
CONFIG_READONLY =           True if os.getenv('ANTICLOUD_READONLY') in ('1',) else False
CONFIG_ACCUMULATE_SUBDIRS = ['DCIM']
# all: all files
# fail: only files for which failed
# fail_and_success: only files for which failed or succeeded (but not files for which nothing had to be done)
CONFIG_LOG = 'fail_and_success'

# TODO like in df/du
def size_human(size):
    #return str(size)+'b'
    step = 0
    while size >= 1024 and step<5:
        step += 1
        size /= 1024
    return '{:.1f}'.format(size)+['b', 'k', 'm', 'g', 't'][step]

def merge_file(src, dst):
    print_to_msg_buf(" merging src and dst:", src, dst)
    # assume that both src and dst exist
    # outer code should check it and if not do accordingly (skip if merging backups or create hardlink if accumulating)
    #if not os.path.exists(src):
    #    print_to_msg_buf(' src does not exist')
    #    return
    if os.stat(src, follow_symlinks=False).st_dev != os.stat(dst, follow_symlinks=False).st_dev:
        print_to_msg_buf(' different filesystems, can\'t merge')
        return False
    if os.path.samefile(src, dst):
        print_to_msg_buf(' same file (already hardlinked)')
        return
    if os.path.getsize(src) != os.path.getsize(dst):
        print_to_msg_buf(' different size, can\'t merge')
        print_to_msg_buf('', os.path.getsize(src), os.path.getsize(dst))
        return False
    if os.stat(dst, follow_symlinks=False).st_nlink>1 and not CONFIG_DST_HARDLINK_COUNT_MULTIPLE=='force':
        if os.stat(src, follow_symlinks=False).st_nlink>1:
            print_to_msg_buf(' src and dst have hardlink count >1, CONFIG_DST_HARDLINK_COUNT_MULTIPLE is not \'force\', can\'t merge')
            return False
        if CONFIG_DST_HARDLINK_COUNT_MULTIPLE == 'swap':
            print_to_msg_buf(' src has hardlink count 1, dst has hardlink count >1, swapping')
            src, dst = dst, src
        else:
            print_to_msg_buf(' src has hardlink count 1, dst has hardlink count >1, CONFIG_DST_HARDLINK_COUNT_MULTIPLE is not \'force\' or \'swap\', can\'t merge')
            return False
    # older mtime is not if
    # - 1970-01-01
    # - has zero time part
    # - is equal to exif time
    if os.path.getmtime(src) > os.path.getmtime(dst) and not CONFIG_DST_MTIME_OLDER=='force':
        if CONFIG_DST_MTIME_OLDER != 'setonsrc':
            print_to_msg_buf(' dst has older mtime, CONFIG_DST_MTIME_OLDER is not \'force\' or \'setonsrc\', can\'t merge')
            return False
        print_to_msg_buf(' dst has older mtime, setting on src')
        if not CONFIG_READONLY:
            os.utime(src, (os.stat(src, follow_symlinks=False).st_atime, os.stat(dst, follow_symlinks=False).st_mtime))
        else:
            print_to_msg_buf(' readonly mode, skipping modifying op')
    if not filecmp.cmp(src, dst):
        print_to_msg_buf(' different contents, can\'t merge')
        return False
    print_to_msg_buf(' hardlinking files')
    if not CONFIG_READONLY:
        # TODO
        os.rename(dst, dst+'-anticloud-hardlink-bak')
        os.link(src, dst)
        os.unlink(dst+'-anticloud-hardlink-bak')
    else:
        print_to_msg_buf(' readonly mode, skipping modifying op')
    return True

def get_filepath_data_for_filedict(filepath):
    return {'stat': os.stat(filepath, follow_symlinks=False)}

def build_filedict(root):
    filedict = {}
    for root_, subdirs, files in os.walk(root):
        for file_ in files:
            filepath = os.path.join(root_, file_)
            filedict[filepath] = get_filepath_data_for_filedict(filepath)
    return filedict

# verify that filepath does not have unwanted changes
# assumes that filepath currently exists (but can be missing in files_dict which means file was created)
def verify_file(files_dict, filepath, allow_new_files=False):
    if not filepath in files_dict:
        if not allow_new_files:
            print(' new file', filepath)
            return False
        return True
    stat = os.stat(filepath, follow_symlinks=False)
    old_stat = files_dict[filepath]['stat']
    del files_dict[filepath]
    if not stat.st_size == old_stat.st_size:
        print(' different size for', filepath)
        return False
    if not stat.st_mtime <= old_stat.st_mtime:
        print(' mtime increased for', filepath)
        return False
    return True

def verify_filedict(files_dict, root, allow_new_files=False):
    print('verifying filedict for', root)
    result = True
    for root_, subdirs, files in os.walk(root):
        for file_ in files:
            filepath = os.path.join(root_, file_)
            if not verify_file(files_dict, filepath, allow_new_files):
                result = False
    if len(files_dict):
        result = False
        print('missing files!')
        for k in files_dict:
            print('', k)
    print('verification successful' if result else 'verification failed, see messages above')
    return result

COMMANDS = {}

def command(name):
    def register(func):
        COMMANDS[name] = func
        return func
    return register

# for conditionally logging operations after result is known
msg_buf = ''

def print_to_msg_buf(*strs):
    global msg_buf
    msg_buf += '\n' + ' '.join(str(str_) for str_ in strs)

def drop_msg_buf():
    global msg_buf
    msg_buf = ''

def print_msg_buf():
    print(msg_buf[1:])
    drop_msg_buf()

# we don't need real date validity check
def is_date(str_):
    parts = str_.split('-')
    return len(parts)==3 and len(parts[0])==4 and parts[0].isdigit() and len(parts[1])==2 and parts[1].isdigit and '01'<=parts[1]<='12' and len(parts[2])==2 and parts[2].isdigit() and '01'<=parts[1]<='31'

# deduplicate pair of backups which can have identical files
# given src and dst, for any file src/subdirs/filename, for which there is identical dst/subdirs/filename, replace dst/subdirs/filename with hardlink to src/subdirs/filename
# can be seen as conditional hardlink copying (`cp -l`) of src over dst, which is only done for subset of files in src for which identical files exist in dst so that replacing them does not change anything in dst
@command('merge-hardlink')
def merge_hardlink(old_backup_root, new_backup_root):
    print('merge_hardlink old_backup={0} new_backup={1}'.format(old_backup_root, new_backup_root))
    result = True
    # build dicts for post check
    old_backup_filedict = {}
    new_backup_filedict = build_filedict(new_backup_root)
    for root, subdirs, files in os.walk(old_backup_root):
        for file_ in files:
            filepath_old_backup = os.path.join(root, file_)
            print_to_msg_buf(filepath_old_backup[len(old_backup_root):])
            old_backup_filedict[filepath_old_backup] = get_filepath_data_for_filedict(filepath_old_backup)
            filepath_new_backup = os.path.join(new_backup_root, root[len(old_backup_root)+1:], file_)
            if not os.path.exists(filepath_new_backup):
                print_to_msg_buf(' does not exist in new_backup tree')
                if CONFIG_LOG == 'all':
                    print_msg_buf()
                else:
                    drop_msg_buf()
                continue
            res = merge_file(filepath_old_backup,
                             filepath_new_backup)
            if CONFIG_LOG == 'all' or (CONFIG_LOG=='fail' and res==False) or (CONFIG_LOG=='fail_and_success' and res is not None):
                print_msg_buf()
            else:
                drop_msg_buf()
    # post check
    if not verify_filedict(old_backup_filedict, old_backup_root):
        result = False
    if not verify_filedict(new_backup_filedict, new_backup_root):
        result = False
    return result

# iterate all yyyy-mm-dd_device-tag backups
# for any backup, iterate all later backups with same device-tag and merge with current
@command('merge-hardlink-all')
def merge_hardlink_all(workdir='.'):
    result = True
    for item1 in sorted(os.listdir(workdir)):
        if not os.path.isdir(os.path.join(workdir, item1)):
            continue
        item1_parts = item1.split('_')
        if len(item1_parts)<2:
            continue
        if not is_date(item1_parts[0]):
            continue
        for item2 in sorted(os.listdir(workdir)):
            if item2 == item1:
                continue
            if not os.path.isdir(os.path.join(workdir, item2)):
                continue
            item2_parts = item2.split('_')
            if len(item2_parts)<2:
                continue
            # same device tag
            if item2_parts[1] != item1_parts[1]:
                continue
            if not is_date(item2_parts[0]):
                continue
            # date of item2 newer
            if item2_parts[0]<item1_parts[0]:
                continue
            if not merge_hardlink(os.path.join(workdir, item1), os.path.join(workdir, item2)):
                result = False
    return result

# collect files from backup to accumulator dir
# given backup (DCIM subdir) and accumulator dir, for each photo in backup (incl. subdirs) check if it is in accumulator; if not, create hardlink in accumulator, else merge
# backup_root: snaphot backup, src in "cp -l src dst" BUT identical files are replaced with ones from dst?
# accumulator: accumulator dir, dst in "cp -l src dst"
@command('accumulate')
def accumulate(backup_root, accumulator):
    print('accumulate backup={0} accumulator={1}'.format(backup_root, accumulator))
    result = True
    snapshot_backup_filedict = build_filedict(backup_root)
    accumulator_filedict = build_filedict(accumulator)
    for root, subdirs, files in os.walk(backup_root):
        # TODO settings
        # skip hidden
        files = [f for f in files if not f.startswith('.')]
        subdirs[:] = [s for s in subdirs if not s.startswith('.')]
        # skip json
        files = [f for f in files if not f.endswith('.json')]
        for file_ in files:
            filepath_snapshot_backup = os.path.join(root, file_)
            print_to_msg_buf(filepath_snapshot_backup[len(backup_root):])
            filepath_accumulator = os.path.join(accumulator, file_)
            if not os.path.exists(filepath_accumulator):
                print_to_msg_buf(' does not exist in accumulator, creating hardlink')
                if not CONFIG_READONLY:
                    os.link(filepath_snapshot_backup, filepath_accumulator)
                else:
                    print_to_msg_buf(' readonly mode, skipping modifying op')
                print_msg_buf()
                continue
            res = merge_file(filepath_snapshot_backup,
                             filepath_accumulator)
            if CONFIG_LOG == 'all' or (CONFIG_LOG=='fail' and res==False) or (CONFIG_LOG=='fail_and_success' and res is not None):
                print_msg_buf()
            else:
                drop_msg_buf()
    if not verify_filedict(snapshot_backup_filedict, backup_root):
        result = False
    if not verify_filedict(accumulator_filedict, accumulator, allow_new_files=True):
        result = False
    return result

# for any yyyy-mm-dd_device-tag backup, accumulate files from DCIM/ subdir to accumulator
# google takeout?
@command('accumulate-all')
def accumulate_all(workdir='.'):
    result = True
    accumulator = os.path.join(workdir, 'accumulator')
    if not os.path.exists(accumulator):
        if not CONFIG_READONLY:
            os.makedirs(accumulator)
        else:
            print(' readonly mode, skipping modifying op')
    for item1 in os.listdir(workdir):
        if not os.path.isdir(os.path.join(workdir, item1)):
            continue
        item1_parts = item1.split('_')
        if len(item1_parts)<2:
            continue
        #item1_device_tag = item1_parts[1]
        if not is_date(item1_parts[0]):
            continue
        for subdir in CONFIG_ACCUMULATE_SUBDIRS:
            item1_subdir = os.path.join(workdir, item1, subdir)
            if os.path.exists(item1_subdir) and os.path.isdir(item1_subdir):
                if not accumulate(item1_subdir, accumulator):
                    result = False
    return result

#@command('list-files-with-hardlink-count-single')

#@command('list-files-unique')

#@command('list-files-shared')

# count size of files which do (not) have hardlinks outside of provided paths
@command('show-size')
def show_size(*paths):
    d_stat = {}
    d_count = {}
    size_unoptimized = 0
    for path in paths:
        print(path)
        for root, subdirs, files in os.walk(path):
            for file_ in files:
                #if not file_.split('.', -1)[-1].lower() in ['jpg', 'jpeg']:
                #if not file_.split('.', -1)[-1].lower() in ['mp4', 'mov']:
                #    continue
                stat = os.stat(os.path.join(root, file_), follow_symlinks=False)
                d_stat[stat.st_ino] = stat
                d_count[stat.st_ino] = d_count.get(stat.st_ino, 0)+1
                #print(os.path.join(root[len(path):], file_))
                #print(d[stat.st_ino])
                size_unoptimized += stat.st_size
    size_unique = 0
    size_shared = 0
    for st_ino in d_stat:
        if d_count[st_ino] == d_stat[st_ino].st_nlink:
            size_unique += d_stat[st_ino].st_size
        else:
            size_shared += d_stat[st_ino].st_size
    print('unique:', size_human(size_unique), 'shared:', size_human(size_shared), 'total:', size_human(size_unique+size_shared), 'unoptimized total:', size_human(size_unoptimized), 'saved by optimization:', size_human(size_unoptimized-(size_unique+size_shared)))

# truncate file to 0 (freeing space even if it has hardlink count >1)
# `echo ''> file`
# but preserve mtime (stat)
#@command('erase')

#@command('set-mtime-from-filename')

#@command('set-mtime-from-metadata')

# make shallow clone of tree using hardlinks
# `cp -al src dst`
@command('clone-hardlink')
def clone_hardlink(src, dst):
    for root, dirs, files in os.walk(src):
        rel_path = os.path.join(os.path.relpath(root, src), '')
        dst_path = os.path.join(dst, rel_path)
        if not CONFIG_READONLY:
            os.makedirs(dst_path, exist_ok=True)
        else:
            print('readonly, skipping modifying op')
        for file_ in files:
            rel_path = os.path.join(os.path.relpath(root, src), file_)
            src_path = os.path.join(src, rel_path)
            dst_path = os.path.join(dst, rel_path)
            if not CONFIG_READONLY:
                os.link(src_path, dst_path)
            else:
                print('readonly, skipping modifying op')

# verify that 2 trees are identical
# `diff -r src dst`
# but allow skipping new files or files with changed mtimes in dst
# src: original
# dst: transformed
# allow_new_files: allow new files in dst
# allow_older_mtimes: allow mtimes on files in dst older than in src
@command('verify')
def verify(src, dst, allow_new_files=False, allow_older_mtimes=False):
    result = True
    src_paths = []
    for root, dirs, files in os.walk(src):
        rel_path = os.path.join(os.path.relpath(root, src), '')
        src_paths.append(rel_path)
        dst_path = os.path.join(dst, rel_path)
        if not os.path.exists(dst_path):
            print('only in src:', rel_path)
            result = False
        for file_ in files:
            rel_path = os.path.join(os.path.relpath(root, src), file_)
            src_paths.append(rel_path)
            src_path = os.path.join(src, rel_path)
            dst_path = os.path.join(dst, rel_path)
            if not os.path.exists(dst_path):
                print('only in src:', rel_path)
                result = False
                continue
            # TODO
            src_stat = os.stat(src_path, follow_symlinks=False)
            dst_stat = os.stat(dst_path, follow_symlinks=False)
            if (dst_stat.st_mtime < src_stat.st_mtime and not allow_older_mtimes) or dst_stat.st_mtime > src_stat.st_mtime:
                print('mtime mismatch:', rel_path)
                result = False
                continue
            if not filecmp.cmp(src_path, dst_path):
                print('different:', rel_path)
                result = False
    if allow_new_files==True:
        return result
    for root, dirs, files in os.walk(dst):
        rel_path = os.path.join(os.path.relpath(root, dst), '')
        if rel_path not in src_paths:
            print('only in dst:', rel_path)
            result = False
        for file_ in files:
            rel_path = os.path.join(os.path.relpath(root, dst), file_)
            if rel_path not in src_paths:
                print('only in dst:', rel_path)
                result = False
    return result

# for any jpeg file, create jpeg-xl, verify that decoded pixmap is identical and metadata is identical, and overwrite original
# TODO files with multiple hardlink count?
# in automation with whole storage optimization with verification, this should also update filedict for verification
# multiple hardlinks, change of filename?
#@command('convert-to-jxl')

# backup using adb only selected brahcnes of tree (DCIM, Download, ...) only after datetime, skip on fail
#@command('adb')

# copy via hardlinking 2 files and all files between them alphanumerically to dst
# last can be filename without path
@command('copy-hardlink-range')
def copy_hardlink_range(first, last, dst_dir):
    src_dir = os.path.dirname(first) or '.'
    basename_first = os.path.basename(first)
    basename_last = os.path.basename(last)
    for item in sorted(os.listdir(src_dir)):
        if os.path.isfile(os.path.join(src_dir, item)) and basename_first<=item<=basename_last:
            print(item)
            if not CONFIG_READONLY:
                os.link(os.join(src_dir, item), os.join(dst_dir, item))
            else:
                print(' readonly mode, skipping modifying op')

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print('commands:', ', '.join(COMMANDS))
        exit()
    cmd, *args = sys.argv[1:]
    func = COMMANDS.get(cmd)
    if not func:
        print('unknown command: ', cmd)
        exit()
    result = func(*args)
    if result==True:
        print('all operations succeeded')
    elif result==False:
        print('some operations failed, check messages above')
    # if None, don't care
    exit(1 if result==False else None)
