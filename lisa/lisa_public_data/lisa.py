import os
from lisa.core.lisa_core import LISA_Core, PACKAGE_PATH, REQURED_DATASET_VERSION
from lisa.core.lisa_core import CONFIG_PATH as base_config_path
import lisa.lisa_public_data.assays as assays
from lisa.lisa_public_data.models import LR_BinarySearch_SampleSelectionModel, LR_ChromatinModel
import numpy as np
from scipy import sparse
import multiprocessing
import configparser

CONFIG_PATH = os.path.join(os.path.dirname(__file__),'config.ini')
_config = configparser.ConfigParser()
_config.read([base_config_path, CONFIG_PATH])

class LISA(LISA_Core):
    '''
lisa.FromGenes
**************

Interface for performing LISA test for TF influence using public chromatin accessibility data. Given just a set of genes, LISA will identify a subset of a large database
of public H3K27ac and DNase profiles that represents a model for multiple chromatin states around those genes. LISA then assesses the influence of TF binding 
on your genes-of-interest vs a sampling of background genes through through those representative datasets, and aggregates the effects to produce a final p-value.

This model is useful for integrating accessibility and binding data when you have strictly a list of associated genes (from scRNA-seq, for example). If you have 
genes-of-interest, as well as regions-of-interest, you may use the more specific test provided by ``lisa.FromRegions``.

*Example:*

.. code:: python

    # Read genelist file
    >>> genes_file = open('./genelist.txt', 'r')
    >>> genes = [x.strip() for x in genes_file.readlines()]
    >>> genes_file.close()
    # Instantiate lisa_regions object. You can pass your regions as a python list of lists, or as the filepath to a bedfile
    >>> lisa_regions = lisa.FromGenes('hg38', cores = 10, isd_method = 'chipseq')
    # Run the LISA test on your genelist
    >>> results, metadata = lisa_regions.predict(genes, num_background_genes = 501)
    # Print results to stdout
    >>> print(results.to_tsv())

**For more, see `user guide <docs/user_guide.rst>`_.**

    '''

    @classmethod
    def document(cls):
        return cls('hg38').get_docs()

    @classmethod
    def get_document_link(cls):
        return "`lisa.FromGenes`_"
    
    def __init__(self, species, cores = 1, assays = ['Direct','H3K27ac','DNase'], isd_method = 'chipseq', **kwargs):
        '''
**lisa.FromGenes(self, species, cores = 1, assays = ['Direct','H3K27ac','DNase'], isd_method = 'chipseq')**
    Initialize the LISA test using public data.

    Params
    ------
    species : {'hg38', 'mm10'}
    cores : int 
        Number of cores to use. For optimal performance, allocate 1, 2, 5, or 10 cores. More cores is faster.
    assays : list of {"Direct","H3K27ac","DNase"}
        default is all tests
    isd_method : {"chipseq", "motifs"}
        Use ChIP-seq data or motifs to mark TF binding locations.
    
    Returns
    -------
    lisa object
        '''

        super().__init__(species, _config, isd_method= isd_method, **kwargs)
        assert(len(assays) > 0), 'Must provide at least one assay to run.'
        assert(all([assay in self._config.get('lisa_params','assays').split(',') for assay in assays])), 'An assay chosen by the user is not a valid choice: \{{}}'.format(self._config.get('lisa_params','assays'))

        num_datasets_selected = int(_config.get('lisa_params', 'num_datasets_selected'))
        num_datasets_selected_anova = int(self._config.get('lisa_params','num_datasets_selected_anova'))

        assert( isinstance(num_datasets_selected, int) )
        assert( isinstance(num_datasets_selected_anova, int) )

        self.num_datasets_selected_anova = num_datasets_selected_anova
        self.num_datasets_selected = num_datasets_selected

        self.cores = self._set_cores(cores)

        assert( num_datasets_selected_anova > num_datasets_selected ), 'Anova must select more datasets than the regression model'
        assert( num_datasets_selected_anova > 0 and num_datasets_selected > 0 ), 'Number of datasets selected must be positive'
        assert(num_datasets_selected_anova < 500)
        assert(num_datasets_selected < 25)

        if self.num_datasets_selected % self.cores != 0:
            self.log.append('''WARNING: You\'ve allocated {} cores with {} datasets selected.
To ensure maximum speed, allocate as many cores as datasets selected.
For better efficiency, make #datasets a multiple of #cores.'''.format(self.cores, self.num_datasets_selected))

        self.data_source = _config.get('paths', 'h5_path').format(package_path = PACKAGE_PATH, species = self.species)

        self.schedule_assays = sorted(list(set(assays)))

        rp_map = 'basic'
        if isinstance(rp_map, str):
            rp_map_styles = self._config.get('lisa_params','rp_map_styles').split(',')
            assert(rp_map in rp_map_styles), 'RP map must be numpy/scipy.sparse array, or be one of provided maps: {}'.format(','.join(rp_map_styles))
        else:
            assert( isinstance(rp_map, np.ndarry) or isinstance(rp_map, scipy.sparse)), 'RP map must be either numpy ndarry or scipy.sparse matrix'
        self.rp_map = rp_map
        self.generate_rp_matrix = rp_map != 'basic'

    def _set_cores(self, cores):
        assert( isinstance(cores, int) and cores >= -1)
        #leave one core out for the rest of us
        max_cores = multiprocessing.cpu_count() - 1
        if cores <= -1:
            cores = max_cores
        #use the minimum number of cores between the user's specificaion, the number of datasets to be processed in parallel, and the number of cores on the machine.
        #this prevents LISA from using more resources than required.
        self.cores = min(cores, max_cores, self.num_datasets_selected)
        return self.cores

    # Change this part
    def _load_factor_binding_data(self):
        super()._load_factor_binding_data('1000')
        
    def _load_rp_map(self):
        if isinstance(self.rp_map, str):
            #self.rp_map = sparse.load_npz(self._config.get('RP_map','matrix').format(package_path = PACKAGE_PATH, species = self.species, style = self.rp_map)).tocsr()
            rp_map_name_params = dict(species = self.species, version = REQURED_DATASET_VERSION, name = self.rp_map)
            
            rp_map_path = self._config.get('paths','rp_map').format(package_path = PACKAGE_PATH, **rp_map_name_params)
            
            if not os.path.exists(rp_map_path):
                try:
                    self.fetch_from_cistrome(self._config.get('downloads', 'rp_maps')\
                        .format(**rp_map_name_params), rp_map_path, is_tar=False)
                except error.URLError as err:
                    self.log.append('Cannot connect to cistrome server, or cistrome server does not have the RP map requested. \nDefaulting to "basic" RP map instead.')
                    rp_map_name_params['name'] = 'basic'
                    rp_map_path = self._config.get('paths','rp_map').format(package_path = PACKAGE_PATH, **rp_map_name_params)
            
            self.rp_map = sparse.load_npz(rp_map_path).tocsr()

        return self.rp_map


    def _get_factor_gene_mask(self):

        factor_genes = self.all_genes.match_user_provided_genes(self.factor_metadata['factor'])

        loc_symbol_dict = dict(zip(factor_genes.get_locations(), factor_genes.get_symbols()))
        self.factor_gene_mask = np.isin(self.rp_map_locs, factor_genes.get_locations())
        #make label vector from label_dict based of gene_loc ordering in rp_map data
        self.factor_mask_keys = [loc_symbol_dict[gene_loc] for gene_loc in self.rp_map_locs[self.factor_gene_mask]]

        return self.factor_gene_mask, self.factor_mask_keys

    def _format_results(self, assay_pvals, assay_info, gene_info_dict, **kwargs):
        
        new_columns = {}
        for assay, info in assay_info.items():
            if 'factor_acc_z_scores' in info:
                z_scores = info.pop('factor_acc_z_scores')
                z_dict = dict(zip(self.factor_mask_keys, z_scores))
                new_columns[assay + 'factor_accessibility_z_score'] = [z_dict.get(factor, 'NA') for factor in self.factor_metadata['factor']]

        return super()._format_results(assay_pvals, assay_info, gene_info_dict, **new_columns, **kwargs)

    def _initialize_assays(self, **assay_kwargs):
        #Add assays to LISA's steps. Each assay follows the same instantiation and prediction calling, making them modular and substitutable.
        #Adding an assay loads the required data for that assay

        try: # if factor gene mask not instantiated
            self.factor_gene_mask
        except AttributeError:
            self._get_factor_gene_mask()

        for assay in self.schedule_assays:
            if assay == 'Direct':
                self.add_assay(
                    assays.PeakRP_Assay(
                        technology = self.isd_method, **assay_kwargs, 
                        metadata = self.link_metadata(self.isd_method),
                        generate_rp_matrix = self.generate_rp_matrix
                    )
                )
            elif assay == 'DNase' or assay == 'H3K27ac':
                self.add_assay(
                    assays.Accesibility_Assay(technology = assay, **assay_kwargs,
                        metadata = self.link_metadata(assay), factor_gene_mask = self.factor_gene_mask,
                        selection_model = LR_BinarySearch_SampleSelectionModel(self.num_datasets_selected_anova, self.num_datasets_selected),
                        chromatin_model = LR_ChromatinModel({'C' : list(10.0**np.arange(-2,4.1,0.5))}, penalty = 'l2'), 
                        cores = self.cores, generate_rp_matrix = self.generate_rp_matrix
                    )
                )
            else:
                raise AssertionError('Invalid assay encountered: {}'.format(str(assay)))

    def predict(self, query_list, background_list = [], background_strategy = 'regulatory', num_background_genes = 3000, seed = 2556):
        '''
    **self.predict(self, query_list, background_list = [], background_strategy = 'regulatory', num_background_genes = 3000, seed = 2556)**
        Predict TF influence given a set of genes.
        
        Params
        ------
        query_list : list
            Genes-of-interest, in either Symbol of RefSeqID format. Must provide between 20 to 500 genes.
        background_list : list
            User-specified list of background genes to compare with query_list. Must contain more genes than query list and entire list will be used. If provided, ```background_strategy``` must be set to "provided".
        background_strategy : {"regulatory","random","provided"}
            Regulatory will sample background genes from a stratified sample of TADs and regulatory states, random will randomly sample from all non-query genes.
        num_background_genes : int
            Number of genes to use as comparison to query genes. More background genes make test slower, but more stable.
        seed : int
            Seed for gene selection and regression model initialization.

        Returns
        -------
        results
            Dictionary with each key representing a table column, sorted by "summary_p_value" field. The dictionary can be passed directly to a the pandas constructor: ``results_df = pd.DataFrame(results.todict())``.
        metadata
            Dictionary with test metadata. Includes query genes provided and background genes that were selected. This metadata dict also contains information on the accessibility datasets that were selected to represent the chromatin landscape around you genes-of-interest, for example, the tissue and cell line from which the profiles were derived.
        
        '''

        super().predict(query_list, background_list=background_list, background_strategy=background_strategy, 
            num_background_genes= num_background_genes, seed=seed)