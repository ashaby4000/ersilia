import csv
import json
import random
import itertools
from ..serve.schema import ApiSchema
from .. import ErsiliaBase


class DataFrame(object):
    def __init__(self, data, columns):
        self.data = data
        self.columns = columns

    @staticmethod
    def _get_delimiter(file_name):
        extension = file_name.split(".")[-1]
        if extension == "tsv":
            return "\t"
        else:
            return ","

    def write(self, file_name, delimiter=None):
        with open(file_name, "w", newline="") as f:
            if delimiter is None:
                delimiter = self._get_delimiter(file_name)
            writer = csv.writer(f, delimiter=delimiter)
            writer.writerow(self.columns)
            for i, row in enumerate(self.data):
                writer.writerow(row)


class ResponseRefactor(ErsiliaBase):
    def __init__(self, config_json):
        ErsiliaBase.__init__(self, config_json=config_json)
        self.logger.debug("Generic output adapter initialized")
        self._expect_meta = None
        self._meta = None

    def _has_meta(self, result):
        if self._expect_meta is not None:
            return self._expect_meta
        try:
            r = result["result"]
            m = result["meta"]
            self._expect_meta = True
        except:
            self._expect_meta = False

    def _get_result(self, result):
        if self._expect_meta is None:
            self._has_meta(result)
        if self._expect_meta:
            return result["result"]
        else:
            return result

    def _get_meta(self, result):
        if self._meta is not None:
            return self._meta
        if self._expect_meta is None:
            self._has_meta(result)
        if self._expect_meta:
            return result["meta"]
        else:
            return None

    def _nullify_meta(self, meta, result):
        m = {}
        one_output = random.choice(result)
        for k, v in one_output.items():
            if meta is None:
                m[k] = None
            else:
                if k not in meta:
                    m[k] = None
                else:
                    m[k] = meta[k]
        return m

    def refactor_response(self, result):
        r = self._get_result(result)
        m = self._get_meta(result)
        m = self._nullify_meta(m, r)
        self._meta = m
        return r


class GenericOutputAdapter(ResponseRefactor):
    def __init__(self, config_json):
        ResponseRefactor.__init__(self, config_json=config_json)
        self.api_schema = None
        self.logger.debug("Generic output adapter initialized")
        self._schema = None

    @staticmethod
    def _is_string(output):
        if type(output) is str:
            return True
        else:
            return False

    @staticmethod
    def _extension(filename):
        return filename.split(".")[-1]

    def _has_extension(self, output, extension):
        if not self._is_string(output):
            return False
        ext = output.split(".")[-1]
        if ext == extension:
            return True
        else:
            return False

    def __pure_dtype(self, k):
        t = self._schema[k]["type"]
        return t

    def __array_shape(self, k):
        s = self._schema[k]["shape"]
        return s[0] # TODO work with tensors

    def __meta_by_key(self, k):
        return self._schema[k]["meta"]

    def __cast_values(self, vals, dtypes, output_keys):
        v = []
        for v_, t_, k_ in zip(vals, dtypes, output_keys):
            if t_ == "array":
                if v_ is None:
                    v_ = [None]*self.__array_shape(k_)
                v += v_
            else:
                v += [v_]
        return v

    def __expand_output_keys(self, vals, output_keys):
        output_keys_expanded = []
        if len(output_keys) == 1:
            merge_key = False
        else:
            merge_key = True
        for v, ok in zip(vals, output_keys):
            m = self.__meta_by_key(ok)
            t = self.__pure_dtype(ok)
            if t == "array":
                assert m is not None
                if v is not None:
                    assert len(m) == len(v)
                if merge_key:
                    output_keys_expanded += ["{0}-{1}".format(ok, m_) for m_ in m]
                else:
                    output_keys_expanded += ["{0}".format(m_) for m_ in m]
            else:
                if merge_key:
                    output_keys_expanded += [ok]
                else:
                    output_keys_expanded += ["f0"]
        return output_keys_expanded

    def _to_dataframe(self, result):
        result = json.loads(result)
        R = []
        output_keys = None
        output_keys_expanded = None
        for r in result:
            inp = r["input"]
            out = r["output"]
            if output_keys is None:
                output_keys = [k for k in out.keys()]
            vals = [out[k] for k in output_keys]
            dtypes = [self.__pure_dtype(k) for k in output_keys]
            if output_keys_expanded is None:
                output_keys_expanded = self.__expand_output_keys(vals, output_keys)
            vals = self.__cast_values(vals, dtypes, output_keys)
            R += [[inp["key"], inp["input"]] + vals]
        columns = ["key", "input"] + output_keys_expanded
        df = DataFrame(data=R, columns=columns)
        return df

    def meta(self):
        if self._meta is None:
            self.logger.error(
                "Meta not available, run some adapations first and it will be inferred atomatically"
            )
        else:
            return self._meta

    def merge(self, subfiles, output_file):
        self.logger.debug(
            "Merging {0} files into {1}".format(len(subfiles), output_file)
        )
        extensions = set([self._extension(x) for x in subfiles + [output_file]])
        assert len(extensions) == 1
        if self._has_extension(output_file, "json"):
            data = []
            for subfile in subfiles:
                with open(subfile, "r") as f:
                    data += json.load(f)
            with open(output_file, "w") as f:
                json.dump(data, f, indent=4)
        else:
            with open(output_file, "w") as fo:
                use_header = True
                for subfile in subfiles:
                    with open(subfile, "r") as fi:
                        if not use_header:
                            next(fi)
                        for l in fi:
                            fo.write(l)
                    use_header = False

    def adapt(self, result, output, model_id=None, api_name=None):
        if model_id is not None and api_name is not None and self.api_schema is None:
            self.api_schema = ApiSchema(model_id=model_id, config_json=self.config_json)
        if self.api_schema is not None:
            if self.api_schema.isfile():
                self._schema = self.api_schema.get_output_by_api(api_name)
        else:
            self.api_schema = None
        if output is not None and self._schema is None:
            raise Exception
        if self._has_extension(output, "json"):
            with open(output, "w") as f:
                json.dump(result, output, indent=4)
        if self._has_extension(output, "csv"):
            df = self._to_dataframe(result)
            df.write(output)
        if self._has_extension(output, "tsv"):
            df = self._to_dataframe(result)
            df.write(output, delimiter="\t")
        return result
