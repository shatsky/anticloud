#!/usr/bin/env python3
import sys
import anticloud

result = True
if not anticloud.merge_hardlink_all(*sys.argv[1:]):
    result = False
if not anticloud.accumulate_all(*sys.argv[1:]):
    result = False
if result:
    print('all operations succeeded')
    exit(0)
else:
    print('some operations failed, check messages above')
    exit(1)
