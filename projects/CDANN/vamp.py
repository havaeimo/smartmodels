import theano
import theano.tensor as T
import models2
import os
from os.path import join as pjoin
import numpy as np
import numpy
from smartlearner import Model
import ipdb
from utils import load_dict_from_json_file, save_dict_to_json_file
from utils import WeightsInitializer
from utils import ACTIVATION_FUNCTIONS
from utils import Timer
from collections import OrderedDict

from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams


class VAMP_smartlearner(Model):

    def __init__(self,
                 random_seed=23455,
                 filter_shapes=[(5, 5), (5, 5)],
                 pool_size=[(2, 2), (2, 2), (2, 2)],
                 pool_stride=[(2, 2), (2, 2), (1, 1)],
                 nkerns=[24, 24],
                 nb_channels=3,
                 image_size=[128, 64],
                 nb_classes=2,
                 batch_size=50,
                 *args, **kwargs):
        super(VAMP_smartlearner, self).__init__(*args, **kwargs)

        self.random_seed = random_seed
        self.filter_shapes = filter_shapes
        self.pool_size = pool_size
        self.pool_stride = pool_stride
        self.nkerns = nkerns

        self.nb_channels = nb_channels
        self.image_size = image_size
        self.nb_classes = nb_classes
        self.batch_size = batch_size
        rng = numpy.random.RandomState(random_seed)
        #input_size = dataset['input_size']
        x_s = T.tensor4('x_s')   # the data is presented as rasterized images
        yf_s = T.ivector('yf_s')  # the labels are presented as 1D vector of
        yd_s = T.ivector('yd_s')  # the labels are presented as 1D vector of
        x_t = T.tensor4('x_t')
        yd_t = T.ivector('yd_t')

        index = T.lscalar()  # index to a [mini]batch                        # [int] labels
        p = T.lscalar()
        ########################################################################################################
        # BUILD ACTUAL MODEL #
        ########################################################################################################
        # Forward prop for the Lf_s
        self.feature_representation_layers = [models2.LeNetConvPoolLayer(rng=rng, layerIdx=0,
                                                                         filter_shape=(nkerns[0], nb_channels, filter_shapes[0][0], filter_shapes[0][1]),
                                                                         image_shape=(batch_size, nb_channels, image_size[0], image_size[1]),
                                                                         activation=T.tanh,
                                                                         pool_size=pool_size[0],
                                                                         pool_stride=pool_stride[0])]
        for h_id in range(1, len(nkerns)):
            nb_channels_h = self.feature_representation_layers[-1].filter_shape[0]
            featuremap_shape = models2.get_channel_shape(self.feature_representation_layers[-1])
            self.feature_representation_layers += [models2.LeNetConvPoolLayer(layerIdx=h_id, rng=rng,
                                                                              filter_shape=(nkerns[h_id], nkerns[h_id - 1], filter_shapes[h_id][0], filter_shapes[h_id][1]),
                                                                              image_shape=(batch_size, nkerns[h_id - 1], featuremap_shape[0], featuremap_shape[1]),
                                                                              activation=T.tanh,
                                                                              pool_size=pool_size[h_id],
                                                                              pool_stride=pool_stride[h_id])]

        last_conv_fm_shape = models2.get_channel_shape(self.feature_representation_layers[-1])
        self.classification_branch = self.feature_representation_layers + [models2.ChannelLogisticRegression(layerIdx=len(nkerns), rng=rng,
                                                                                                             filter_shape=(nb_classes, nkerns[-1], last_conv_fm_shape[0], last_conv_fm_shape[1]),
                                                                                                             image_shape =(batch_size, nkerns[-1], last_conv_fm_shape[0], last_conv_fm_shape[1]))]

    @property
    def parameters(self):
        params = OrderedDict()
        for layer in self.classification_branch:

            for param in layer.params:
                params[param.name] = param
        return params

    def use(self, X):
        probs = self.get_model_output(X)

        return T.argmax(probs, axis=1, keepdims=False)

    def save(self, path):
        if not os.path.isdir(path):
            os.makedirs(path)

        hyperparameters = {
            'random_seed': self.random_seed,
            'filter_shapes': self.filter_shapes,
            'pool_size': self.pool_size,
            'pool_stride': self.pool_stride,
            'nkerns': self.nkerns,

            'nb_channels': self.nb_channels,
            'image_size': self.image_size,
            'nb_classes': self.nb_classes,
            'batch_size': self.batch_size
        }

        save_dict_to_json_file(pjoin(path, "meta.json"), {"name": self.__class__.__name__})
        save_dict_to_json_file(pjoin(path, "hyperparams.json"), hyperparameters)

        params = {param_name: param.get_value() for param_name, param in self.parameters.items()}
        np.savez(pjoin(path, "params.npz"), **params)

    @classmethod
    def load(cls, path):
        meta = load_dict_from_json_file(pjoin(path, "meta.json"))
        assert meta['name'] == cls.__name__

        hyperparams = load_dict_from_json_file(pjoin(path, "hyperparams.json"))

        model = cls(**hyperparams)
        parameters = np.load(pjoin(path, "params.npz"))
        for param_name, param in model.parameters.items():
            param.set_value(parameters[param_name])

        return model

    # def initialize(self, weights_initialization=None):
    #    if weights_initialization is None:
    #        weights_initialization = WeightsInitializer().uniform
    #
    #    self.W.set_value(weights_initialization(self.W.get_value().shape))
    #
    #    if not self.tied_weights:
    #        self.V.set_value(weights_initialization(self.V.get_value().shape))

    def fprop(self, input):
        #from ipdb import set_trace as dbg
        #import theano.printing as printing
        #input = printing.Print('input')(input)
        # dbg()
        #input = input.reshape((self.batch_size, self.image_size[0], self.image_size[1],self.nb_channels))
        input = input.dimshuffle(0, 3, 1, 2)
        next_layer_input = input
        for layer in self.classification_branch:
            next_layer_input = layer.fprop(next_layer_input)
        return next_layer_input

    def get_model_output(self, inputs):
        output = self.fprop(input=inputs)
        return output

    def get_last_hiddenlayer_output(self, inputs):
        inputs = inputs.dimshuffle(0, 3, 1, 2)
        next_layer_input = inputs

        for layer in self.classification_branch:
            next_layer_input = layer.fprop(next_layer_input)
        return next_layer_input