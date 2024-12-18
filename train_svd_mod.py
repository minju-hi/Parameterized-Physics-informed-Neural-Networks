import torch
from torch.autograd import Variable
from config import get_config, get_params
from model import P2INN_phase2_svd
from Loss_f import PDE_cal
import numpy as np
import random
import torch.backends.cudnn as cudnn
from sklearn.metrics import explained_variance_score, max_error
import os
import utils

def main():
    args = get_config()
    random_seed = args.seed
    
    torch.manual_seed(random_seed)
    torch.cuda.manual_seed(random_seed)
    torch.cuda.manual_seed_all(random_seed)
    np.random.seed(random_seed)
    cudnn.benchmark = False
    cudnn.deterministic = True
    random.seed(random_seed)
    
    device = torch.device(args.device)

    print("=============[Deivce Info]==============")
    print("- Use Device :", device)
    print("- Available cuda devices :", torch.cuda.device_count())
    print("- Current cuda device :", torch.cuda.current_device())
    print("- Name of cuda device :", torch.cuda.get_device_name(device))
    print("========================================\n")
    
    epoch = 15
    load_epoch = 20000
    load_range = args.load_range

    initial_condition = args.init_cond
    pde_type = args.pde_type
    
    beta, nu, rho = args.beta, args.nu, args.rho
        
    PRETRAIN_PATH = f'./param/{initial_condition}/checkpoint_all_{str(load_range)}_{str(random_seed)}/P2INN_{str(load_epoch)}.pt'
    loaded_params = torch.load(PRETRAIN_PATH)
    
    bias_2 = loaded_params['dec_layer_2.bias']
    bias_3 = loaded_params['dec_layer_3.bias']
    bias_4 = loaded_params['dec_layer_4.bias']
    bias_5 = loaded_params['dec_layer_5.bias']
    bias_6 = loaded_params['dec_layer_6.bias']
    biases = (bias_2, bias_3, bias_4, bias_5, bias_6)
    
    svd_names = ['dec_layer_2.weight', 'dec_layer_3.weight', 'dec_layer_4.weight', 'dec_layer_5.weight', 'dec_layer_6.weight']
    uus, vvs, sss = [], [], []
    
    for svd_name in svd_names:
        u, s, v = torch.svd(loaded_params[svd_name])
        uus.append(u)
        sss.append(s)
        vvs.append(v.t())
    
    net = P2INN_phase2_svd(uus, vvs, sss, biases).to(device)
    net.load_state_dict(torch.load(PRETRAIN_PATH), strict=False)
    
    model_size = get_params(net)
    for name, param in net.named_parameters():
        if name in loaded_params.keys():
            if 'dec_layer_' not in name: 
                param.requires_grad = False
            if 'dec_layer_1' in name: 
                param.requires_grad = False
            if 'modvec' in name:
                param.requires_grad = True
                
            ## [OPTION] let first and last layers of the decoder train ##                
            # if ('dec_layer_' not in name): 
            #     param.requires_grad = False
            # if 'last_' in name:
            #     param.requires_grad = True
            # if 'modvec' in name:
            #     param.requires_grad = True

    print("=============[Train Info]===============")
    print(f"- PDE type : {pde_type}")
    print(f"- Initial condition : {initial_condition}")
    print(f"- Coefficient : Beta {beta} | Nu {nu} | Rho {rho}")
    print(f"- Model size : {model_size}")
    print(f"- Trainable parameters : {utils.count_parameters(net)}")
    print("========================================\n")

    print("=============[Model Info]===============\n")
    print(net)
    print("========================================\n")
  
    f_dataloader, u_dataloader, bd_dataloader, test_dataloader = utils.get_dataloader_only_one_w_bd(initial_condition, pde_type, beta, nu, rho)   

    mse_cost_function = torch.nn.MSELoss()
    optimizer = torch.optim.Adam(net.parameters())
    
    ## START Training ##
    for EPOCH in range(epoch):
        net.train()

        loss_saver_f = 0
        loss_saver_u = 0
        loss_saver_bd = 0

        # Collocation Condition
        for samples_f in f_dataloader:

            x_f, t_f, u_f, beta_f, nu_f, rho_f, eq_f = samples_f
            x_f     = x_f.clone().detach().requires_grad_(True).to(device)
            t_f     = t_f.clone().detach().requires_grad_(True).to(device)
            u_f     = u_f.to(device)
            beta_f  = beta_f.to(device)
            nu_f    = nu_f.to(device)
            rho_f   = rho_f.to(device)
            eq_f    = eq_f.to(device).float()

            all_zeros = np.zeros((len(x_f), 1))
            all_zeros = Variable(torch.from_numpy(all_zeros).float(), requires_grad=False).to(device)

            pde_output_f = PDE_cal(eq_f, x_f, t_f, beta_f, nu_f, rho_f, net)

            cost_f = mse_cost_function(pde_output_f, all_zeros)
            loss_saver_f += cost_f.item()

        # Initial Condition
        for samples_u in u_dataloader:

            x_u, t_u, u_u, beta_u, nu_u, rho_u, eq_u = samples_u

            x_u     = x_u.clone().detach().requires_grad_(True).to(device)
            t_u     = t_u.clone().detach().requires_grad_(True).to(device)
            u_u     = u_u.to(device)
            beta_u  = beta_u.to(device)
            nu_u    = nu_u.to(device)
            rho_u   = rho_u.to(device)
            eq_u    = eq_u.to(device).float()

            u_pred_u = net(eq_u, x_u, t_u)
            
            all_zeros = np.zeros((len(x_u), 1))
            all_zeros = Variable(torch.from_numpy(all_zeros).float(), requires_grad=False).to(device)

            pde_output_u = PDE_cal(eq_u, x_u, t_u, beta_u, nu_u, rho_u, net)
            cost_u = mse_cost_function(pde_output_u, all_zeros)
            cost_gt = mse_cost_function(u_u, u_pred_u)

            loss_saver_u += cost_u.item()
            loss_saver_u += cost_gt.item()

        for samples_bd in bd_dataloader:

            x_data_lb, t_data_lb, x_data_ub, t_data_ub, beta_bd, nu_bd, rho_bd, eq_bd = samples_bd

            x_data_lb   = x_data_lb.clone().detach().requires_grad_(True).to(device)
            t_data_lb   = t_data_lb.clone().detach().requires_grad_(True).to(device)
            x_data_ub   = x_data_ub.clone().detach().requires_grad_(True).to(device)
            t_data_ub   = t_data_ub.clone().detach().requires_grad_(True).to(device)

            beta_bd     = beta_bd.to(device)
            nu_bd       = nu_bd.to(device)
            rho_bd      = rho_bd.to(device)
            eq_bd       = eq_bd.to(device).float()

            u_pred_lb = net(eq_bd, x_data_lb, t_data_lb)
            u_pred_ub = net(eq_bd, x_data_ub, t_data_ub)

            cost_bd   = torch.mean((u_pred_lb - u_pred_ub) ** 2)
            loss_saver_bd += cost_bd.item()
            
        cost_total = cost_f + cost_u + cost_gt + cost_bd
            
        optimizer.zero_grad()
        cost_total.backward()
        optimizer.step()

        
        with torch.autograd.no_grad():
            net.eval()

            u_pred_test_list = []
            u_test_list = []
            
            for samples_test in test_dataloader:

                x_test, t_test, u_test, beta_test, nu_test, rho_test, eq_test = samples_test
                
                x_test      = x_test.clone().detach().requires_grad_(True).to(device)
                t_test      = t_test.clone().detach().requires_grad_(True).to(device)
                u_test      = u_test.clone().detach().requires_grad_(True).to(device)
                beta_test   = beta_test.clone().detach().requires_grad_(True).to(device)
                nu_test     = nu_test.clone().detach().requires_grad_(True).to(device)
                rho_test    = rho_test.clone().detach().requires_grad_(True).to(device)
                eq_test     = eq_test.to(device).float()
                
                u_pred_test = net(eq_test, x_test, t_test)
                
                if len(u_pred_test_list) == 0:
                    u_pred_test_list = u_pred_test[:, 0]
                    u_test_list = u_test[:, 0]
                    
                else:
                    u_pred_test_list = torch.cat((u_pred_test_list, u_pred_test[:, 0]), dim=0)
                    u_test_list = torch.cat((u_test_list, u_test[:, 0]), dim=0)
                    
            u_pred_test_tensor = u_pred_test_list
            u_test_tensor = u_test_list

            L2_error_norm = torch.linalg.norm(u_pred_test_tensor-u_test_tensor, 2, dim = 0)
            L2_true_norm = torch.linalg.norm(u_test_tensor, 2, dim = 0)

            L2_absolute_error = torch.mean(torch.abs(u_pred_test_tensor-u_test_tensor))
            L2_relative_error = L2_error_norm / L2_true_norm
            
            u_test_tensor = u_test_tensor.cpu()
            u_pred_test_tensor = u_pred_test_tensor.cpu()
            
            Max_err = max_error(u_test_tensor, u_pred_test_tensor)
            Ex_var_score = explained_variance_score(u_test_tensor, u_pred_test_tensor)
            
            print('L2_abs_err :', L2_absolute_error.item())
            print('L2_rel_err :', L2_relative_error.item())
            print('Max_error :', Max_err)
            print('Variance_score :', Ex_var_score)                 
                
        train_loss = (loss_saver_f) + (loss_saver_u) + (loss_saver_bd)

        print('Epoch number :', EPOCH)
        print('Training_loss :', train_loss)
        print('loss f, loss_u, loss_bd :', loss_saver_f, loss_saver_u, loss_saver_bd)
        print('=================================================================')        




if __name__ == "__main__":
    main()


