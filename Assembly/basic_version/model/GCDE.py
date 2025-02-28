import torch
import torch.nn.functional as F
import torch.nn as nn
import controldiffeq
from .vector_fields import *
import numpy as np

class NeuralGCDE(nn.Module):
    def __init__(self, func_f, func_g, input_channels, hidden_channels, output_channels, num_nodes, num_layers, embed_dim, atol, rtol, solver, horizon):
        super(NeuralGCDE, self).__init__()
        self.num_node = num_nodes
        self.input_dim = input_channels
        self.hidden_dim = hidden_channels
        self.output_dim = output_channels
        self.num_layers = num_layers
        self.horizon = horizon

        self.default_graph = True
        self.node_embeddings = nn.Parameter(torch.randn(self.num_node, embed_dim), requires_grad=True)
        
        self.func_f = func_f
        self.func_g = func_g
        self.solver = solver
        self.atol = atol
        self.rtol = rtol

        #predictor
        self.end_conv = nn.Conv2d(1, self.horizon * self.output_dim, kernel_size=(1, self.hidden_dim), bias=True)

        self.init_type = 'fc'
        if self.init_type == 'fc':
            self.initial_h = torch.nn.Linear(self.input_dim, self.hidden_dim)
            self.initial_z = torch.nn.Linear(self.input_dim, self.hidden_dim)
        elif self.init_type == 'conv':
            self.start_conv_h = nn.Conv2d(in_channels=input_channels,
                                            out_channels=hidden_channels,
                                            kernel_size=(1,1))
            self.start_conv_z = nn.Conv2d(in_channels=input_channels,
                                            out_channels=hidden_channels,
                                            kernel_size=(1,1))
            
        self.global_pool = nn.AdaptiveAvgPool1d((1))

    def forward(self, spline, times):
        #source: B, T_1, N, D
        #target: B, T_2, N, D
        #supports = F.softmax(F.relu(torch.mm(self.nodevec1, self.nodevec1.transpose(0,1))), dim=1)

        if self.init_type == 'fc':
            h0 = self.initial_h(spline.evaluate(times[0]))
            z0 = self.initial_z(spline.evaluate(times[0]))
        elif self.init_type == 'conv':
            h0 = self.start_conv_h(spline.evaluate(times[0]).transpose(1,2).unsqueeze(-1)).transpose(1,2).squeeze()
            z0 = self.start_conv_z(spline.evaluate(times[0]).transpose(1,2).unsqueeze(-1)).transpose(1,2).squeeze()

        # print(torch.max(h0))

        z_t = controldiffeq.cdeint_gde_dev(dX_dt=spline.derivative, #dh_dt
                                   h0=h0,
                                   z0=z0,
                                   func_f=self.func_f,
                                   func_g=self.func_g,
                                   t=times,
                                   method=self.solver,
                                   atol=self.atol,
                                   rtol=self.rtol)
        
        # print(torch.max(z_t))


        # init_state = self.encoder.init_hidden(source.shape[0])
        # output, _ = self.encoder(source, init_state, self.node_embeddings)      #B, T, N, hidden
        # output = output[:, -1:, :, :]                                   #B, 1, N, hidden
        z_T = z_t[-1:,...].transpose(0,1)

        #CNN based predictor
        output = self.end_conv(z_T)                         #B, T*C, N, 1
        output = output.squeeze(-1).reshape(-1, self.horizon, self.output_dim, self.num_node)
        output = output.permute(0, 1, 3, 2)  

        return output