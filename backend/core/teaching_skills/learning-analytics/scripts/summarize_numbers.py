import sys
import json
import statistics

values = [float(value) for value in sys.argv[1:]]
if not values:
    raise ValueError('请提供至少一个数字')
print(json.dumps({'count': len(values), 'sum': sum(values), 'mean': statistics.mean(values), 'median': statistics.median(values)}, ensure_ascii=False))
