from sys import stderr
from contextlib import contextmanager
from scipy import sparse
import numpy as np
from collections import defaultdict, OrderedDict

def ragged_array_to_sparse_matrix(indices, values, col_length):
    return sparse.hstack([
        sparse.csc_matrix(
            (val_column,
            (index_column, np.zeros(len(val_column)))),
            shape = (col_length, 1)
        )
        for index_column, val_column in zip(indices, values)
    ])

class LoadingBar:
    
    def __init__(self, label, increments, length = 25, cold_start = False):
        self.increments = increments
        self.length = length
        self.label = label
        self.progress = 0
        self.cold_start = cold_start
        
    def __str__(self):
        if self.cold_start:
            self.cold_start = False
        else:
            self.increment()
        completed_steps = int(self.progress / self.increments * self.length)
        if completed_steps >= self.length:
            return '{}: [{}]'.format(self.label, "="*completed_steps) + '\n' if self.is_finished() else ''
        else:
            return '{}: [{}>{}]'.format(self.label, "="*completed_steps, " "*(self.length - completed_steps - 1))
    
    def increment(self):
        if not self.is_finished():
            self.progress += 1
        
    def is_finished(self):
        return self.progress >= self.increments


class Log:

    def __init__(self, target = stderr, verbose = True):
        self.target = target
        self.indents = 0
        self.verbose = verbose    

    @contextmanager
    def section(self, header):
        try:
            self.start_section(header)
            yield self
        finally:
            self.end_section()

    def start_section(self, section_header):
        self.append(section_header)
        self.indents += 1

    def end_section(self):
        self.indents -= 1 

    def append(self, text, end = '\n', update_line = False):
        linestart = '\r' if update_line else ''
        if (isinstance(self.verbose, bool) and self.verbose == True) or (isinstance(self.verbose, int) and self.indents < self.verbose):
            print(linestart + '\t'*self.indents + str(text), 
                end = '' if update_line else end, 
                file = self.target)


class LISA_Results:

    @classmethod
    def fromdict(cls, **kwargs):
        d = kwargs
        return LISA_Results(list(d.keys()), list(d.values()))

    def __init__(self, keys, columns):
        self.results_headers = keys
        self.results_rows = self._transpose_table(columns)

    def get_colnum(self, colname):
        try:
            return np.argwhere(np.array(self.results_headers) == colname)[0][0]
        except IndexError:
            raise IndexError('Column {} not in results table'.format(str(colname)))

    def sortby(self, key, add_rank = False):

        if isinstance(key, str):
            key = self.get_colnum(key)

        self.results_rows = sorted(self.results_rows, key = lambda col : col[key])

        if add_rank:
            row_ranks = range(1, len(self) + 1)
            try:
                self.update_column('Rank', row_ranks)
            except IndexError:
                self.add_column('Rank', row_ranks, 0)

        return self

    def __len__(self):
        return len(self.results_rows)

    @staticmethod
    def _transpose_table(table):
        return [list(l) for l in list(zip(*table))]

    def todict(self):
        return dict( zip( self.results_headers, self._transpose_table(self.results_rows)))

    def update_column(self, name, data):

        colnum = self.get_colnum(name)
        
        for row, value in zip(self.results_rows, data):
            row[colnum] = value


    def add_column(self, name, data, column_num = 0):

        assert( not name in self.results_headers ), 'Column already exists'

        if column_num == -1:
            self.results_headers.append(name)
            for row, value in zip(self.results_rows, data):
                row.append(value)

        else:
            self.results_headers.insert(column_num, name)
            for row, value in zip(self.results_rows, data):
                row.insert(column_num, value)

        return self

    def subset(self, rows):

        if isinstance(rows, int):
            rows = [rows]

        return LISA_Results(self.results_headers, self._transpose_table([
            self.results_rows[row] for row in rows
        ]))

    def to_tsv(self, top_n = 200):

        output_lines = self.subset(range(top_n))
        return '\n'.join([
            '\t'.join([str(value) for value in line])
            for line in [output_lines.results_headers, *output_lines.results_rows]
        ])

    def filter_rows(self, filter_func, colname):

        colnum = self.get_colnum(colname)
        subset_rows = [
            rownum for rownum, row in enumerate(self.results_rows)
            if filter_func(row[colnum])
        ]

        return self.subset(subset_rows)
